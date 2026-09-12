class SimulatorAdapter:
    """Development-only device; state is kept separately from desired/reported settings."""

    def __init__(self, cache, camera_id):
        self.cache = cache
        self.key = f"vigilay:simulator:{camera_id}"

    def probe(self):
        if self.cache.hget(self.key, "offline") == b"1":
            raise ConnectionError("Simulador desconectado")
        self.cache.hsetnx(self.key, "motion_sensitivity", "50")
        return {"model": "Vigilay Simulator", "firmware": "1", "simulated": True}

    def get_capabilities(self):
        self.probe()
        return {
            "motion_sensitivity": {
                "supported": True,
                "readable": True,
                "writable": True,
                "metadata": {"min": 0, "max": 100, "simulated": True},
            }
        }

    def get_current_settings(self):
        self.probe()
        return {"motion_sensitivity": int(self.cache.hget(self.key, "motion_sensitivity"))}

    def apply_settings(self, values):
        self.probe()
        if set(values) != {"motion_sensitivity"}:
            raise ValueError("Capacidad no soportada")
        value = values["motion_sensitivity"]
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("Sensibilidad inválida")
        self.cache.hset(self.key, "motion_sensitivity", str(value))
