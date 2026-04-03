# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Device plugin registry for Hera.

Scans the devices/ folder, imports all modules, collects DeviceBase subclasses,
and maps Hercules device classes to plugin implementations.
"""

import importlib
import logging
import os
from typing import Optional, Type

from .device_base import DeviceBase, DeviceContext, GenericDevice

logger = logging.getLogger(__name__)


class DeviceRegistry:
    """
    Auto-discovers device plugins from the devices/ directory.

    Usage:
        registry = DeviceRegistry()
        registry.load()
        # Create a device instance for a Hercules device
        device = registry.create_device(devclass="DSP", devnum="0700", devtype="3270")
    """

    def __init__(self, devices_dir: Optional[str] = None):
        if devices_dir is None:
            devices_dir = os.path.join(os.path.dirname(__file__), "devices")
        self.devices_dir = devices_dir
        # Maps devclass string -> plugin class (e.g. "DSP" -> CpuDevice)
        self._class_map: dict[str, Type[DeviceBase]] = {}

    def load(self) -> int:
        """
        Scan devices/ folder and load all device plugins.
        Returns the number of successfully loaded plugins.
        """
        self._class_map.clear()
        if not os.path.isdir(self.devices_dir):
            logger.warning("Devices directory not found: %s", self.devices_dir)
            return 0

        count = 0
        for fname in sorted(os.listdir(self.devices_dir)):
            if fname.startswith("_") or not fname.endswith(".py"):
                continue
            module_name = f"{__package__}.devices.{fname[:-3]}"
            try:
                module = importlib.import_module(module_name)
                # Find all DeviceBase subclasses defined in this module
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, DeviceBase)
                        and attr is not DeviceBase
                        and attr is not GenericDevice
                        and attr.__module__ == module_name
                    ):
                        for devclass in attr.device_classes:
                            if devclass in self._class_map:
                                logger.warning(
                                    "Device class %s already registered by %s, skipping %s",
                                    devclass, self._class_map[devclass].__name__, attr.__name__
                                )
                            else:
                                self._class_map[devclass] = attr
                                logger.debug("Registered %s -> %s", devclass, attr.__name__)
                count += 1
            except Exception as e:
                logger.warning("Failed to load device module %s: %s", module_name, e)

        logger.info("Loaded %d device plugin(s), %d class mappings", count, len(self._class_map))
        return count

    def _build_context(
        self,
        devclass: str,
        devnum: str = "",
        devtype: str = "",
        label: str = "",
        api_client=None,
        devport: int = 0,
        config=None,
    ) -> DeviceContext:
        return DeviceContext(
            devclass=devclass,
            devnum=devnum,
            devtype=devtype,
            label=label,
            api_client=api_client,
            devport=devport,
            config=config,
            host=config.host if config is not None else "127.0.0.1",
        )

    def _instantiate(self, devclass: str, context: DeviceContext) -> DeviceBase:
        plugin_class = self._class_map.get(devclass)
        if plugin_class is not None:
            return plugin_class(context=context)
        return GenericDevice(context=context)

    def create_device(
        self,
        devclass: str,
        devnum: str,
        devtype: str,
        label: str = "",
        api_client=None,
        devport: int = 0,
        config=None,
    ) -> DeviceBase:
        """
        Create a device instance for a Hercules device.
        Returns a plugin instance if one matches, otherwise a GenericDevice.
        """
        context = self._build_context(
            devclass=devclass,
            devnum=devnum,
            devtype=devtype,
            label=label,
            api_client=api_client,
            devport=devport,
            config=config,
        )
        return self._instantiate(devclass, context)

    def create_cpu_device(self, api_client=None, config=None) -> DeviceBase:
        """Create the CPU device (not address-based)."""
        context = self._build_context(
            devclass="CPU",
            devtype="",
            devnum="",
            label="CPU",
            api_client=api_client,
            config=config,
        )
        return self._instantiate("CPU", context)

    def create_console_device(self, api_client=None, config=None) -> DeviceBase:
        """Create the Hercules console device (not address-based)."""
        context = self._build_context(
            devclass="CONSOLE",
            devtype="Console",
            devnum="",
            label="Console",
            api_client=api_client,
            config=config,
        )
        return self._instantiate("CONSOLE", context)

    @property
    def registered_classes(self) -> list[str]:
        return list(self._class_map.keys())
