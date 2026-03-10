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
"""In-memory implementation of FederationManager."""


import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from flwr.common.typing import Federation
from flwr.proto.federation_pb2 import (  # pylint: disable=E0611
    Account,
    Invitation,
    Member,
)

from .federation_manager import FederationManager


@dataclass
class _FederationRecord:
    name: str
    description: str
    # flwr_aid -> role ("owner" | "member")
    members: dict[str, str] = field(default_factory=dict)
    # node_ids in this federation
    node_ids: set[int] = field(default_factory=set)
    archived: bool = False


@dataclass
class _InvitationRecord:
    federation_name: str
    inviter_flwr_aid: str
    inviter_account_name: str
    invitee_flwr_aid: str
    invitee_account_name: str
    status: str  # "pending" | "accepted" | "rejected" | "revoked"
    created_at: str
    status_changed_at: str


class InMemoryFederationManager(FederationManager):
    """In-memory FederationManager implementation.

    Stores federations, memberships, nodes, and invitations in memory.
    Suitable for local SuperLink deployments and testing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # federation_name -> _FederationRecord
        self._federations: dict[str, _FederationRecord] = {}
        # list of invitations
        self._invitations: list[_InvitationRecord] = []
        # flwr_aid -> account_name (populated on federation create/accept)
        self._accounts: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def exists(self, federation: str) -> bool:
        """Check if a federation exists."""
        with self._lock:
            rec = self._federations.get(federation)
            return rec is not None and not rec.archived

    def has_member(self, flwr_aid: str, federation: str) -> bool:
        """Check if the given account is a member of the federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            return flwr_aid in rec.members

    def filter_nodes(self, node_ids: set[int], federation: str) -> set[int]:
        """Return the subset of node_ids that belong to the federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            return node_ids & rec.node_ids

    def has_node(self, node_id: int, federation: str) -> bool:
        """Check if a node is in the federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            return node_id in rec.node_ids

    def get_federations(self, flwr_aid: str) -> list[Federation]:
        """Get federations of which the account is a member (name/description only)."""
        with self._lock:
            result = []
            for rec in self._federations.values():
                if not rec.archived and flwr_aid in rec.members:
                    result.append(
                        Federation(
                            name=rec.name,
                            description=rec.description,
                            members=[],
                            nodes=[],
                            runs=[],
                            archived=rec.archived,
                        )
                    )
            return result

    def get_details(self, federation: str) -> Federation:
        """Get full details of a federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None:
                raise ValueError(f"Federation '{federation}' does not exist.")

        # Fetch live run/node data from linkstate (outside lock to avoid deadlock)
        member_aids = list(rec.members.keys())
        runs = list(self.linkstate.get_run_info(flwr_aids=member_aids))
        nodes = list(
            self.linkstate.get_node_info(node_ids=list(rec.node_ids))
            if rec.node_ids
            else []
        )

        with self._lock:
            members_proto = [
                Member(
                    account=Account(
                        id=aid,
                        name=self._accounts.get(aid, aid),
                    ),
                    role=role,
                )
                for aid, role in rec.members.items()
            ]
        return Federation(
            name=rec.name,
            description=rec.description,
            members=members_proto,
            nodes=nodes,
            runs=runs,
            archived=rec.archived,
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_federation(
        self, flwr_aid: str, name: str, description: str
    ) -> Federation:
        """Create a new federation owned by flwr_aid."""
        with self._lock:
            if name in self._federations:
                raise ValueError(f"Federation '{name}' already exists.")
            rec = _FederationRecord(
                name=name,
                description=description,
                members={flwr_aid: "owner"},
            )
            self._federations[name] = rec

        return Federation(
            name=rec.name,
            description=rec.description,
            members=[
                Member(
                    account=Account(
                        id=flwr_aid,
                        name=self._accounts.get(flwr_aid, flwr_aid),
                    ),
                    role="owner",
                )
            ],
            nodes=[],
            runs=[],
            archived=False,
        )

    def archive_federation(self, flwr_aid: str, name: str) -> None:
        """Archive a federation. Only the owner can archive it."""
        with self._lock:
            rec = self._federations.get(name)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{name}' does not exist.")
            if rec.members.get(flwr_aid) != "owner":
                raise ValueError(
                    f"Account '{flwr_aid}' is not the owner of federation '{name}'."
                )
            rec.archived = True

    def add_supernode(self, flwr_aid: str, federation: str, node_id: int) -> None:
        """Add a SuperNode to a federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            if flwr_aid not in rec.members:
                raise ValueError(
                    f"Account '{flwr_aid}' is not a member of federation '{federation}'."
                )
            rec.node_ids.add(node_id)

    def remove_supernode(self, flwr_aid: str, federation: str, node_id: int) -> None:
        """Remove a SuperNode from a federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            if flwr_aid not in rec.members:
                raise ValueError(
                    f"Account '{flwr_aid}' is not a member of federation '{federation}'."
                )
            rec.node_ids.discard(node_id)

    # ------------------------------------------------------------------
    # Invitation operations
    # ------------------------------------------------------------------

    def create_invitation(
        self, flwr_aid: str, federation: str, invitee_flwr_aid: str
    ) -> None:
        """Create an invitation for invitee_flwr_aid to join federation."""
        with self._lock:
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            if flwr_aid not in rec.members:
                raise ValueError(
                    f"Account '{flwr_aid}' is not a member of federation '{federation}'."
                )
            if invitee_flwr_aid in rec.members:
                raise ValueError(
                    f"Account '{invitee_flwr_aid}' is already a member of '{federation}'."
                )
            # Check for an existing pending invitation
            for inv in self._invitations:
                if (
                    inv.federation_name == federation
                    and inv.invitee_flwr_aid == invitee_flwr_aid
                    and inv.status == "pending"
                ):
                    raise ValueError(
                        f"A pending invitation for '{invitee_flwr_aid}' in "
                        f"'{federation}' already exists."
                    )
            now = datetime.now(timezone.utc).isoformat()
            self._invitations.append(
                _InvitationRecord(
                    federation_name=federation,
                    inviter_flwr_aid=flwr_aid,
                    inviter_account_name=self._accounts.get(flwr_aid, flwr_aid),
                    invitee_flwr_aid=invitee_flwr_aid,
                    invitee_account_name=self._accounts.get(
                        invitee_flwr_aid, invitee_flwr_aid
                    ),
                    status="pending",
                    created_at=now,
                    status_changed_at=now,
                )
            )

    def list_invitations(
        self, flwr_aid: str
    ) -> tuple[list[Invitation], list[Invitation]]:
        """Return (created_by_me, received_by_me) pending invitation lists."""
        with self._lock:
            created: list[Invitation] = []
            received: list[Invitation] = []
            for inv in self._invitations:
                if inv.status == "pending":
                    proto = Invitation(
                        federation_name=inv.federation_name,
                        inviter=Account(
                            id=inv.inviter_flwr_aid,
                            name=inv.inviter_account_name,
                        ),
                        invitee=Account(
                            id=inv.invitee_flwr_aid,
                            name=inv.invitee_account_name,
                        ),
                        status=inv.status,
                        created_at=inv.created_at,
                        status_changed_at=inv.status_changed_at,
                    )
                    if inv.inviter_flwr_aid == flwr_aid:
                        created.append(proto)
                    elif inv.invitee_flwr_aid == flwr_aid:
                        received.append(proto)
            return created, received

    def accept_invitation(self, flwr_aid: str, federation: str) -> None:
        """Accept a pending invitation, adding flwr_aid as a member."""
        with self._lock:
            inv = self._find_pending_invitation(flwr_aid, federation, as_invitee=True)
            inv.status = "accepted"
            inv.status_changed_at = datetime.now(timezone.utc).isoformat()
            rec = self._federations.get(federation)
            if rec is None or rec.archived:
                raise ValueError(f"Federation '{federation}' does not exist.")
            rec.members[flwr_aid] = "member"

    def reject_invitation(self, flwr_aid: str, federation: str) -> None:
        """Reject a pending invitation."""
        with self._lock:
            inv = self._find_pending_invitation(flwr_aid, federation, as_invitee=True)
            inv.status = "rejected"
            inv.status_changed_at = datetime.now(timezone.utc).isoformat()

    def revoke_invitation(
        self, flwr_aid: str, federation: str, invitee_flwr_aid: str
    ) -> None:
        """Revoke a pending invitation (only the inviter can revoke)."""
        with self._lock:
            for inv in self._invitations:
                if (
                    inv.federation_name == federation
                    and inv.inviter_flwr_aid == flwr_aid
                    and inv.invitee_flwr_aid == invitee_flwr_aid
                    and inv.status == "pending"
                ):
                    inv.status = "revoked"
                    inv.status_changed_at = datetime.now(timezone.utc).isoformat()
                    return
            raise ValueError(
                f"No pending invitation from '{flwr_aid}' for '{invitee_flwr_aid}' "
                f"in federation '{federation}'."
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def register_account(self, flwr_aid: str, account_name: str) -> None:
        """Register an account name ↔ flwr_aid mapping.

        Called by the control servicer whenever an account's identity is known
        (e.g. on federation creation or node registration) so that invitation
        proto messages can display human-readable names.
        """
        with self._lock:
            self._accounts[flwr_aid] = account_name

    def resolve_flwr_aid(self, account_name: str) -> str | None:
        """Return the flwr_aid for the given account_name, or None if unknown."""
        with self._lock:
            for aid, name in self._accounts.items():
                if name == account_name:
                    return aid
            return None

    def _find_pending_invitation(
        self, flwr_aid: str, federation: str, *, as_invitee: bool
    ) -> _InvitationRecord:
        """Find a pending invitation; raises ValueError if not found."""
        for inv in self._invitations:
            if inv.federation_name != federation or inv.status != "pending":
                continue
            match = (
                inv.invitee_flwr_aid == flwr_aid
                if as_invitee
                else inv.inviter_flwr_aid == flwr_aid
            )
            if match:
                return inv
        role = "invitee" if as_invitee else "inviter"
        raise ValueError(
            f"No pending invitation for '{flwr_aid}' as {role} in '{federation}'."
        )
