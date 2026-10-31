"""Central policy for GPS / location telemetry. Pure Python, no third-party imports, so it is unit-testable anywhere.

Who may see location data (enforced in the BACKEND by iotapi.py; the UI only reflects what the server returns):
  * "full"          - roles holding the `location.read` grant in permissions.py (CEO, plus the Operations roles you authorise: proposed COO and service manager).
  * "assigned_only" - technicians: only for vehicles that have an OPEN (not completed/closed) service ticket assigned to them. Their whole IoT view is
                      limited to those vehicles; access ends when the ticket is completed or reassigned.
  * "none"          - everybody else. Location metrics are removed from every response, chart, alert and CSV export, and asking for one by name is refused (403).

What counts as a location metric is decided by NAME (devices send arbitrary metric names): see LOCATION_METRIC_PATTERN. Because a name-based rule can be bypassed by an
oddly named metric, set IOT_EXTRA_LOCATION_METRICS=comma,separated,names on the server to add your devices' own location metric names.
"""
import re

DONE_STATUSES = ('COMPLETED', 'CUSTOMER_CONFIRMATION', 'CLOSED')
# POSIX-compatible (works in Python `re` and PostgreSQL `~`). Names are already restricted to lower_snake_case at ingest.
BASE_LOCATION_NAMES = ('latitude', 'longitude', 'lat', 'lng', 'lon', 'long', 'altitude', 'heading', 'bearing', 'coordinates', 'coordinate')
BASE_LOCATION_PREFIXES = ('gps', 'location', 'geo', 'position')


def location_pattern(extra: str = '') -> str:
    """Regex (string) matching location metric names. `extra` = comma-separated additional exact metric names from the environment."""
    names = list(BASE_LOCATION_NAMES)
    for x in (extra or '').split(','):
        x = x.strip().lower()
        if re.fullmatch(r'[a-z][a-z0-9_]{1,39}', x) and x not in names: names.append(x)
    prefixes = '|'.join(p + '(_[a-z0-9_]*)?' for p in BASE_LOCATION_PREFIXES)
    return '^(' + '|'.join(names) + '|' + prefixes + ')$'


def is_location_metric(metric: str, extra: str = '') -> bool:
    return bool(re.match(location_pattern(extra), (metric or '').strip().lower()))


def location_access(role: str, has_location_grant: bool) -> str:
    """'full' | 'assigned_only' | 'none'. `has_location_grant` = permissions.can(role, 'location.read')."""
    if has_location_grant: return 'full'
    if role == 'technician': return 'assigned_only'
    return 'none'


# Vehicles a technician is currently working on: an open ticket assigned to them whose vehicle reference matches the vehicle's registration
# (spaces / hyphens / case ignored, the same rule that makes registration numbers unique). Parameters: (user_id, list_of_done_statuses).
ASSIGNED_VEHICLES_SQL = ("select v.id from office_dashboard.fleet_vehicles v join office_dashboard.service_tickets k"
                         " on regexp_replace(upper(coalesce(k.vehicle_reference,'')),'[^A-Z0-9]','','g') = regexp_replace(upper(v.registration_number),'[^A-Z0-9]','','g')"
                         " where k.assigned_to=%s and not k.archived and not v.archived and k.status <> all(%s)")


def vehicle_scope(role: str, user_id: str, column: str):
    """SQL condition + params limiting `column` (a vehicle id column) to the technician's assigned vehicles; None for roles that are not scoped."""
    if role != 'technician': return None
    return f'{column} in ({ASSIGNED_VEHICLES_SQL})', [user_id, list(DONE_STATUSES)]
