import logging
import time

from redis import Redis
from sqlalchemy import select
from vigilay_adapters.simulator import SimulatorAdapter

from vigilay.config import settings
from vigilay.db import system_session
from vigilay.models import AuditLog, Camera, CameraCapability, CameraSetting, DeviceCommand, utcnow


def process_one():
    if not settings().enable_simulator:
        return False
    with system_session() as db:
        command = db.scalar(
            select(DeviceCommand)
            .join(Camera, Camera.id == DeviceCommand.camera_id)
            .where(
                DeviceCommand.status == "PENDING",
                Camera.integration_type == "SIMULATOR",
            )
            .order_by(DeviceCommand.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if command is None:
            return False
        camera = db.get(Camera, command.camera_id)
        if camera.integration_type != "SIMULATOR":
            return False
        command.status = "RUNNING"
        try:
            with Redis.from_url(settings().redis_url, socket_timeout=3) as cache:
                adapter = SimulatorAdapter(cache, camera.id)
                adapter.probe()
                for key, value in adapter.get_capabilities().items():
                    cap = db.get(CameraCapability, (camera.id, key))
                    if cap is None:
                        cap = CameraCapability(
                            tenant_id=camera.tenant_id, camera_id=camera.id, capability_key=key
                        )
                        db.add(cap)
                    cap.supported, cap.readable, cap.writable = (
                        value["supported"],
                        value["readable"],
                        value["writable"],
                    )
                    cap.metadata_json = value["metadata"]
                if command.command == "APPLY_SETTINGS":
                    adapter.apply_settings(command.payload_json)
                elif command.command != "PROBE":
                    raise ValueError("Comando no soportado")
                reported = adapter.get_current_settings()
                for key, value in reported.items():
                    item = db.get(CameraSetting, (camera.id, key))
                    if item is None:
                        item = CameraSetting(
                            tenant_id=camera.tenant_id,
                            camera_id=camera.id,
                            setting_key=key,
                            desired_value_json=value,
                        )
                        db.add(item)
                    item.reported_value_json = value
                    item.sync_status = "SYNCED" if item.desired_value_json == value else "DRIFTED"
                camera.status = "ONLINE"
                matched = all(reported.get(k) == v for k, v in command.payload_json.items())
                command.status = "SUCCEEDED" if matched else "FAILED"
                if not matched:
                    command.sanitized_error = "La configuración reportada difiere de la solicitada"
        except Exception:
            command.status = "FAILED"
            command.sanitized_error = "No se pudo ejecutar el comando en el simulador"
            camera.status = "OFFLINE"
            for item in db.scalars(
                select(CameraSetting).where(CameraSetting.camera_id == camera.id)
            ):
                item.sync_status = "ERROR"
        command.completed_at = utcnow()
        db.add(
            AuditLog(
                tenant_id=camera.tenant_id,
                action="CAMERA_COMMAND_" + command.status,
                resource_type="command",
                resource_id=command.id,
            )
        )
        db.commit()
        return True


def main():
    logging.basicConfig(level=logging.INFO)
    with Redis.from_url(settings().redis_url, socket_timeout=3) as cache:
        while True:
            try:
                cache.set("vigilay:worker:heartbeat", "ok", ex=30)
                if not process_one():
                    time.sleep(1)
            except Exception:
                logging.error('{"service":"worker","event_type":"RETRY"}')
                time.sleep(3)


if __name__ == "__main__":
    main()
