import logging
import aiohttp
from aiohttp import FormData
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.components.lock import LockEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

DOMAIN = "ufanet_doorphone"
_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://dom.ufanet.ru"
LOGIN_ENDPOINT = f"{API_BASE_URL}/login/"
GET_DOORPHONES_ENDPOINT = f"{API_BASE_URL}/api/v0/skud/shared"
OPEN_DOORPHONE_ENDPOINT = f"{API_BASE_URL}/api/v0/skud/shared/{{id}}/open/"

class UfanetAPI:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = None
        self.cookie = None

    async def authenticate(self):
        """Authenticates with the API and retrieves the cookie."""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        params = {
            "next": "/office/skud/",
            "contract": self.username,
            "password": self.password
        }
        data = FormData()
        data.add_field('next', '/office/skud/')
        data.add_field('contract', self.username)
        data.add_field('password', self.password)

        async with aiohttp.ClientSession() as session:
            self.session = session
            async with session.post(LOGIN_ENDPOINT, data=data) as response:
                if response.status == 200:
                    self.cookie = session.cookie_jar
                    _LOGGER.debug("Authentication successful, cookies saved.")
                else:
                    _LOGGER.error("Authentication failed. Status code: %s", response.status)
                    raise Exception("Authentication failed")

    async def get_doorphones(self):
        """Gets the list of doorphones."""
        if not self.cookie:
            await self.authenticate()
        async with aiohttp.ClientSession(cookie_jar=self.cookie) as session:
            self.session = session
            async with self.session.get(GET_DOORPHONES_ENDPOINT) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug("Fetched doorphones: %s", data)
                    return data
                elif response.status == 401:
                    _LOGGER.warning("Cookie expired, re-authenticating.")
                    await self.authenticate()
                    return await self.get_doorphones()
                else:
                    _LOGGER.error("Failed to fetch doorphones. Status code: %s", response.status)
                    raise Exception("Failed to fetch doorphones")

    async def open_doorphone(self, doorphone_id):
        """Opens a specific doorphone."""
        if not self.cookie:
            await self.authenticate()
        url = OPEN_DOORPHONE_ENDPOINT.format(id=doorphone_id)

        async with aiohttp.ClientSession(cookie_jar=self.cookie) as session:
            self.session = session
            async with self.session.get(url) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("result", False)
                elif response.status == 401:
                    _LOGGER.warning("Cookie expired, re-authenticating.")
                    await self.authenticate()
                    return await self.open_doorphone(doorphone_id)
                else:
                    _LOGGER.error("Failed to open doorphone. Status code: %s", response.status)
                    raise Exception("Failed to open doorphone")

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration using YAML (if applicable)."""
    _LOGGER.debug("async_setup called for YAML configuration.")
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up Ufanet Doorphone locks from a config entry."""
    _LOGGER.debug("async_setup_entry for lock platform called with entry: %s", entry)

    entry_id = entry.entry_id
    api = hass.data[DOMAIN][entry_id]["api"]
    coordinator = hass.data[DOMAIN][entry_id]["coordinator"]

    doorphones = coordinator.data
    _LOGGER.debug("Fetched doorphones from coordinator: %s", doorphones)

    if not doorphones:
        _LOGGER.warning("No doorphones found from API.")
        return

    locks = [UfanetLock(api, doorphone) for doorphone in doorphones]
    _LOGGER.debug("Created lock entities: %s", [lock.name for lock in locks])
    async_add_entities(locks)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration."""
    _LOGGER.debug("async_unload_entry called for entry: %s", entry.entry_id)
    hass.data[DOMAIN].pop(entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, ["lock"])

class UfanetLock(LockEntity):
    """Representation of a Ufanet Doorphone as a Lock."""

    def __init__(self, api, doorphone):
        self._api = api
        self._doorphone = doorphone
        self._name = doorphone.get("string_view", "Unknown Doorphone")
        self._id = doorphone["id"]

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return f"ufanet_doorphone_{self._id}"

    @property
    def is_locked(self):
        """Doorphones are stateless, always return False."""
        return False

    async def async_unlock(self, **kwargs):
        """Handle the unlock action to open the doorphone."""
        _LOGGER.debug("Unlocking doorphone: %s", self._id)
        success = await self._api.open_doorphone(self._id)
        if success:
            _LOGGER.info("Doorphone %s opened successfully.", self._name)
        else:
            _LOGGER.error("Failed to open doorphone %s.", self._name)

# async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
#     """Set up the lock platform."""
#     _LOGGER.debug("async_setup_platform called with discovery_info: %s", discovery_info)
#     if discovery_info is None:
#         _LOGGER.error("No discovery_info passed to async_setup_platform.")
#         return
#
#     entry_id = discovery_info["entry_id"]
#     api = hass.data[DOMAIN][entry_id]["api"]
#     coordinator = hass.data[DOMAIN][entry_id]["coordinator"]
#
#     doorphones = coordinator.data
#     if not doorphones:
#         _LOGGER.warning("No doorphones found from API.")
#         return
#
#     _LOGGER.debug("Creating lock entities for doorphones: %s", doorphones)
#     locks = [UfanetLock(api, doorphone) for doorphone in doorphones]
#     async_add_entities(locks)
