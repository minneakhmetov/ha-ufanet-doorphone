import logging
import requests
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.components.lock import LockEntity

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
            "Content-Type": "application/x-www-form-urlencoded",
           # "Content-Length": "4608",
        }
        params = {
            "next": "/office/skud/",
            "contract": self.username,
            "password": self.password
        }
        self.session = requests.Session()
        response = self.session.post(LOGIN_ENDPOINT, data=params)
        if response.status_code == 200:
            self.cookie = self.session.cookies
            _LOGGER.debug("Authentication successful, cookies saved.")
        else:
            _LOGGER.error("Authentication failed. Status code: %s", response.status)
            raise Exception("Authentication failed")

    async def get_doorphones(self):
        """Gets the list of doorphones."""
        if not self.session or self.cookie:
            await self.authenticate()

        response = self.session.get(GET_DOORPHONES_ENDPOINT, cookies=self.cookie)

        if response.status_code == 200:
            data = response.json()
            _LOGGER.debug("Fetched doorphones: %s", data)
            return data
        elif response.status_code == 401:
            _LOGGER.warning("Cookie expired, re-authenticating.")
            await self.authenticate()
            return await self.get_doorphones()
        else:
            _LOGGER.error("Failed to fetch doorphones. Status code: %s", response.status)
            raise Exception("Failed to fetch doorphones")

    async def open_doorphone(self, doorphone_id):
        """Opens a specific doorphone."""
        if not self.session or self.cookie:
            await self.authenticate()

        url = OPEN_DOORPHONE_ENDPOINT.format(id=doorphone_id)

        response = self.session.get(url, cookies=self.cookie)

        if response.status_code == 200:
            result = response.json()
            return result.get("result", False)
        elif response.status_code == 401:
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

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    _LOGGER.debug("async_setup_entry called with config entry: %s", entry.data)
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    api = UfanetAPI(username, password)
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=api.get_doorphones,
        update_interval=timedelta(minutes=10),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator
    }

    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("Setting up platforms for domain: %s", DOMAIN)
    hass.config_entries.async_setup_platforms(entry, ["lock"])
    return True

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

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the lock platform."""
    _LOGGER.debug("async_setup_platform called with discovery_info: %s", discovery_info)
    if discovery_info is None:
        _LOGGER.error("No discovery_info passed to async_setup_platform.")
        return

    entry_id = discovery_info["entry_id"]
    api = hass.data[DOMAIN][entry_id]["api"]
    coordinator = hass.data[DOMAIN][entry_id]["coordinator"]

    doorphones = coordinator.data
    if not doorphones:
        _LOGGER.warning("No doorphones found from API.")
        return

    _LOGGER.debug("Creating lock entities for doorphones: %s", doorphones)
    locks = [UfanetLock(api, doorphone) for doorphone in doorphones]
    async_add_entities(locks)
