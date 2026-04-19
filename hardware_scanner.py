"""
Hardware Scanner — classifies the machine into a tier used by Metis
to pick the right Ollama model (or behavior profile).
"""

import psutil


def get_hardware_tier() -> str:
    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    if total_ram_gb < 16:
        return "Lite"
    elif total_ram_gb < 32:
        return "Pro"
    else:
        return "Sovereign"


def get_hardware_report() -> dict:
    vm = psutil.virtual_memory()
    return {
        "tier": get_hardware_tier(),
        "total_ram_gb": round(vm.total / (1024 ** 3), 2),
        "available_ram_gb": round(vm.available / (1024 ** 3), 2),
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }
