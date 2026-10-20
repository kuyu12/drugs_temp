"""Read-only Medical Devices API extraction into pandas."""
from .client import Client as MedicalDevicesClient, Config as MedicalDevicesConfig
from .pandas_ingestion import fetch_medical_devices_dataframe

__version__ = "0.2.0"
__all__ = ["MedicalDevicesClient", "MedicalDevicesConfig", "fetch_medical_devices_dataframe"]
