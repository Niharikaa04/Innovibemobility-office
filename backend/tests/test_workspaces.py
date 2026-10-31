import pytest
import permissions
from workspaces import MODULES, RecordIn

def test_module_registry_has_core_missing_modules():
    for name in ('startup-metrics','kpi-center','business-overview','reports-and-analytics','customers-fleets-oems',
                 'sales-and-marketing','quotations-and-orders','revenue-and-invoices','expenses','payments-and-receivables',
                 'budget-and-forecast','documents','settings','integrations'):
        assert name in MODULES

def test_unknown_module_is_not_granted_by_registry():
    assert 'made-up-module' not in MODULES

def test_record_validation_trims_and_defaults():
    record=RecordIn(title='  Service visit  ')
    assert record.title == 'Service visit'
    assert record.status == 'Open'
    assert record.fields == {}

def test_record_rejects_empty_title_and_negative_amount():
    with pytest.raises(Exception): RecordIn(title='  ')
    with pytest.raises(Exception): RecordIn(title='Invoice', amount=-1)

def test_rbac_is_deny_by_default_for_unknown_role_and_permission():
    assert permissions.can('unknown-role','reports.read') is False
    assert permissions.can('employee','settings.admin') is False

def test_record_rejects_oversized_or_complex_custom_fields():
    with pytest.raises(Exception):
        RecordIn(title='Record', fields={f'k{i}': i for i in range(61)})
    with pytest.raises(Exception):
        RecordIn(title='Record', fields={'nested': {'not': 'allowed'}})

def test_registry_maps_provider_dependent_modules_without_claiming_live_connections():
    for name in ('waba-whatsapp','email','unified-inbox','evcare-ai-diagnostics','iot-and-telemetry','system-monitoring'):
        assert name in MODULES
