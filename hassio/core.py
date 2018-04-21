"""Main file for HassIO."""
import asyncio
import logging

from .coresys import CoreSysAttributes
from .const import (
    STARTUP_SYSTEM, STARTUP_SERVICES, STARTUP_APPLICATION, STARTUP_INITIALIZE)
from .utils.dt import fetch_timezone

_LOGGER = logging.getLogger(__name__)


class HassIO(CoreSysAttributes):
    """Main object of hassio."""

    def __init__(self, coresys):
        """Initialize hassio object."""
        self.coresys = coresys

    async def setup(self):
        """Setup HassIO orchestration."""
        # update timezone
        if self.sys_config.timezone == 'UTC':
            self.sys_config.timezone = await fetch_timezone(self._websession)

        # supervisor
        await self.sys_supervisor.load()

        # hostcontrol
        await self._host_control.load()

        # Load homeassistant
        await self.sys_homeassistant.load()

        # Load addons
        await self.sys_addons.load()

        # rest api views
        await self.sys_api.load()

        # load last available data
        await self.sys_updater.load()

        # load last available data
        await self.sys_snapshots.load()

        # load services
        await self.sys_services.load()

        # start dns forwarding
        self.sys_create_task(self.sys_dns.start())

        # start addon mark as initialize
        await self.sys_addons.auto_boot(STARTUP_INITIALIZE)

    async def start(self):
        """Start HassIO orchestration."""
        # on release channel, try update itself
        # on dev mode, only read new versions
        if not self.sys_dev and self.sys_supervisor.need_update:
            if await self.sys_supervisor.update():
                return
        else:
            _LOGGER.info("Ignore Hass.io auto updates on dev channel")

        # start api
        await self.sys_api.start()
        _LOGGER.info("Start API on %s", self.sys_docker.network.supervisor)

        try:
            # HomeAssistant is already running / supervisor have only reboot
            if self.sys_hardware.last_boot == self.sys_config.last_boot:
                _LOGGER.info("Hass.io reboot detected")
                return

            # reset register services / discovery
            self.sys_services.reset()

            # start addon mark as system
            await self.sys_addons.auto_boot(STARTUP_SYSTEM)

            # start addon mark as services
            await self.sys_addons.auto_boot(STARTUP_SERVICES)

            # run HomeAssistant
            if self.sys_homeassistant.boot:
                await self.sys_homeassistant.start()

            # start addon mark as application
            await self.sys_addons.auto_boot(STARTUP_APPLICATION)

            # store new last boot
            self.sys_config.last_boot = self.sys_hardware.last_boot
            self.sys_config.save_data()

        finally:
            # Add core tasks into scheduler
            await self.sys_tasks.load()

            # If landingpage / run upgrade in background
            if self.sys_homeassistant.version == 'landingpage':
                self.sys_create_task(self.sys_homeassistant.install())

            _LOGGER.info("Hass.io is up and running")

    async def stop(self):
        """Stop a running orchestration."""
        # don't process scheduler anymore
        self.sys_scheduler.suspend = True

        # process async stop tasks
        await asyncio.wait([
            self.sys_api.stop(),
            self.sys_dns.stop(),
            self.sys_websession.close(),
            self.sys_websession_ssl.close()
        ])
