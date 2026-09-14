class SimulatorAdapter:
    """Development-only device backed by a caller-owned persistent state mapping."""

    def __init__(self, state):
        self.state = state

    def probe(self):
        if self.state.get("offline", False):
            raise ConnectionError("Simulador desconectado")
        self.state.setdefault("motion_sensitivity", 50)
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
        return {"motion_sensitivity": int(self.state["motion_sensitivity"])}

    def apply_settings(self, values):
        self.probe()
        if set(values) != {"motion_sensitivity"}:
            raise ValueError("Capacidad no soportada")
        value = values["motion_sensitivity"]
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("Sensibilidad inválida")
        self.state["motion_sensitivity"] = value
