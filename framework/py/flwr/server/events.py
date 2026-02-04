# Copyright 2024 Flower Labs GmbH. All Rights Reserved.
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
"""Event dispatcher for real-time training events."""


import threading
import time
from collections import defaultdict
from queue import Empty, Full, Queue

from flwr.proto.event_pb2 import Event, EventType


class EventDispatcher:
    """Global event dispatcher for broadcasting training events."""

    def __init__(self) -> None:
        """Initialize the event dispatcher."""
        self._subscribers: dict[int, list[Queue[Event]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, run_id: int) -> Queue[Event]:
        """Subscribe to events for a specific run.

        Parameters
        ----------
        run_id : int
            The run ID to subscribe to.

        Returns
        -------
        Queue[Event]
            A queue that will receive events for this run.
        """
        queue: Queue[Event] = Queue()
        with self._lock:
            self._subscribers[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: int, queue: Queue[Event]) -> None:
        """Unsubscribe from events.

        Parameters
        ----------
        run_id : int
            The run ID to unsubscribe from.
        queue : Queue[Event]
            The queue to remove.
        """
        with self._lock:
            if run_id in self._subscribers:
                try:
                    self._subscribers[run_id].remove(queue)
                except ValueError:
                    pass
                if not self._subscribers[run_id]:
                    del self._subscribers[run_id]

    def emit(self, event: Event) -> None:
        """Emit an event to all subscribers.

        Parameters
        ----------
        event : Event
            The event to emit.
        """
        run_id = event.run_id
        with self._lock:
            subscribers = self._subscribers.get(run_id, []).copy()

        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except (Full, ValueError):
                # Queue is full or closed, skip this subscriber
                pass

    def emit_event(
        self,
        run_id: int,
        event_type: EventType.ValueType,
        node_id: int = 0,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Create and emit an event.

        Parameters
        ----------
        run_id : int
            The run ID.
        event_type : EventType
            The type of event.
        node_id : int
            The node ID (default: 0 for ServerApp).
        metadata : dict[str, str] | None
            Optional metadata dictionary.
        """
        event = Event(
            timestamp=time.time(),
            run_id=run_id,
            node_id=node_id,
            event_type=event_type,
        )
        if metadata:
            event.metadata.update(metadata)
        self.emit(event)

    def get_events(self, queue: Queue[Event], timeout: float = 0.5) -> list[Event]:
        """Get all available events from the queue.

        Parameters
        ----------
        queue : Queue[Event]
            The queue to read from.
        timeout : float
            Maximum time to wait for first event.

        Returns
        -------
        list[Event]
            List of events.
        """
        events: list[Event] = []

        # Wait for first event with timeout
        try:
            event = queue.get(timeout=timeout)
            events.append(event)
        except Empty:
            return events

        # Get remaining events without blocking
        while True:
            try:
                event = queue.get_nowait()
                events.append(event)
            except Empty:
                break

        return events


# Global singleton instance
_event_dispatcher: EventDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_event_dispatcher() -> EventDispatcher:
    """Get the global event dispatcher instance.

    Returns
    -------
    EventDispatcher
        The global event dispatcher.
    """
    global _event_dispatcher  # noqa: PLW0603 pylint: disable=global-statement
    if _event_dispatcher is None:
        with _dispatcher_lock:
            if _event_dispatcher is None:
                _event_dispatcher = EventDispatcher()
    return _event_dispatcher
