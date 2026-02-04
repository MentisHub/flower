# Copyright 2025 Flower Labs GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for event dispatcher."""


import time

from flwr.proto.event_pb2 import Event, EventType
from flwr.server.events import EventDispatcher, get_event_dispatcher


def test_event_dispatcher_subscribe() -> None:
    """Test that subscription creates a queue."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1

    # Execute
    queue = dispatcher.subscribe(run_id)

    # Assert
    assert queue is not None
    assert queue.empty()


def test_event_dispatcher_emit() -> None:
    """Test that events are emitted to subscribers."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1
    queue = dispatcher.subscribe(run_id)

    # Execute
    event = Event(
        timestamp=time.time(),
        run_id=run_id,
        node_id=0,
        event_type=EventType.EVENT_TYPE_ROUND_STARTED,
    )
    event.metadata["round"] = "1"
    dispatcher.emit(event)

    # Assert
    assert not queue.empty()
    received_event = queue.get_nowait()
    assert received_event.run_id == run_id
    assert received_event.event_type == EventType.EVENT_TYPE_ROUND_STARTED
    assert received_event.metadata["round"] == "1"


def test_event_dispatcher_emit_event() -> None:
    """Test the emit_event convenience method."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1
    queue = dispatcher.subscribe(run_id)

    # Execute
    dispatcher.emit_event(
        run_id=run_id,
        event_type=EventType.EVENT_TYPE_ROUND_FIT_AGGREGATED,
        node_id=0,
        metadata={"round": "2", "loss": "0.5", "accuracy": "0.9"},
    )

    # Assert
    assert not queue.empty()
    event = queue.get_nowait()
    assert event.run_id == run_id
    assert event.event_type == EventType.EVENT_TYPE_ROUND_FIT_AGGREGATED
    assert event.node_id == 0
    assert event.metadata["round"] == "2"
    assert event.metadata["loss"] == "0.5"
    assert event.metadata["accuracy"] == "0.9"


def test_event_dispatcher_multiple_subscribers() -> None:
    """Test that events are sent to multiple subscribers."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1
    queue1 = dispatcher.subscribe(run_id)
    queue2 = dispatcher.subscribe(run_id)

    # Execute
    dispatcher.emit_event(
        run_id=run_id,
        event_type=EventType.EVENT_TYPE_ROUND_STARTED,
        metadata={"round": "1"},
    )

    # Assert
    assert not queue1.empty()
    assert not queue2.empty()
    event1 = queue1.get_nowait()
    event2 = queue2.get_nowait()
    assert event1.event_type == event2.event_type


def test_event_dispatcher_different_runs() -> None:
    """Test that events are only sent to matching run_id subscribers."""
    # Prepare
    dispatcher = EventDispatcher()
    queue_run1 = dispatcher.subscribe(run_id=1)
    queue_run2 = dispatcher.subscribe(run_id=2)

    # Execute
    dispatcher.emit_event(
        run_id=1,
        event_type=EventType.EVENT_TYPE_ROUND_STARTED,
        metadata={"round": "1"},
    )

    # Assert
    assert not queue_run1.empty()
    assert queue_run2.empty()


def test_event_dispatcher_unsubscribe() -> None:
    """Test that unsubscribe stops receiving events."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1
    queue = dispatcher.subscribe(run_id)

    # Execute
    dispatcher.emit_event(
        run_id=run_id,
        event_type=EventType.EVENT_TYPE_ROUND_STARTED,
        metadata={"round": "1"},
    )
    _ = queue.get_nowait()  # Clear the queue

    dispatcher.unsubscribe(run_id, queue)

    dispatcher.emit_event(
        run_id=run_id,
        event_type=EventType.EVENT_TYPE_ROUND_COMPLETED,
        metadata={"round": "1"},
    )

    # Assert
    assert queue.empty()


def test_event_dispatcher_get_events() -> None:
    """Test get_events retrieves all available events."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1
    queue = dispatcher.subscribe(run_id)

    # Execute
    for i in range(5):
        dispatcher.emit_event(
            run_id=run_id,
            event_type=EventType.EVENT_TYPE_ROUND_STARTED,
            metadata={"round": str(i)},
        )

    events = dispatcher.get_events(queue, timeout=0.1)

    # Assert
    assert len(events) == 5
    for i, event in enumerate(events):
        assert event.metadata["round"] == str(i)


def test_event_dispatcher_node_events() -> None:
    """Test events with specific node_id."""
    # Prepare
    dispatcher = EventDispatcher()
    run_id = 1
    queue = dispatcher.subscribe(run_id)
    node_id = 12345

    # Execute
    dispatcher.emit_event(
        run_id=run_id,
        event_type=EventType.EVENT_TYPE_NODE_FIT_COMPLETED,
        node_id=node_id,
        metadata={"round": "1", "loss": "0.5", "accuracy": "0.9"},
    )

    # Assert
    events = dispatcher.get_events(queue, timeout=0.1)
    assert len(events) == 1
    assert events[0].node_id == node_id
    assert events[0].event_type == EventType.EVENT_TYPE_NODE_FIT_COMPLETED


def test_get_event_dispatcher_singleton() -> None:
    """Test that get_event_dispatcher returns same instance."""
    # Execute
    dispatcher1 = get_event_dispatcher()
    dispatcher2 = get_event_dispatcher()

    # Assert
    assert dispatcher1 is dispatcher2
