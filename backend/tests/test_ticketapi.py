import pytest
from ticketapi import TicketIn, TransitionIn
import tickets

def test_ticket_input_validation_and_normalization():
    item=TicketIn(title='  Brake check  ',priority='HIGH')
    assert item.title=='Brake check'
    assert item.priority=='HIGH'
    with pytest.raises(Exception): TicketIn(title='  ')
    with pytest.raises(Exception): TicketIn(title='Valid',priority='P0')

def test_ticket_transition_api_uses_existing_lifecycle_rules():
    assert tickets.can_transition('NEW','TRIAGED','service_manager')
    assert not tickets.can_transition('NEW','CLOSED','technician')
    assert TransitionIn(status='CLOSED').status=='CLOSED'
