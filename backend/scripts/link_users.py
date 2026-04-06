import sys
import os

# Add the parent directory to sys.path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import User, Budget, BudgetMember
from app.database import operations_engine, identity_engine
from sqlmodel import Session, select


def link_user_to_budget(user_email: str, budget_id: int, role: str = "editor"):
    with Session(identity_engine) as session_id:
        user = session_id.exec(select(User).where(User.email == user_email)).first()
        if not user:
            print(f"❌ User with email '{user_email}' not found.")
            return

    with Session(operations_engine) as session_ops:
        budget = session_ops.get(Budget, budget_id)
        if not budget:
            print(f"❌ Budget with ID {budget_id} not found.")
            return

        # Check if already a member
        existing_member = session_ops.exec(
            select(BudgetMember).where(
                BudgetMember.budget_id == budget_id,
                BudgetMember.user_id == user.id
            )
        ).first()

        if existing_member:
            print(f"⚠️ User '{user_email}' is already a member of budget '{budget.name}' (ID: {budget_id}) with role '{existing_member.role}'.")
            confirm = input("Do you want to update the role? [y/N]: ")
            if confirm.lower() == 'y':
                existing_member.role = role
                session_ops.add(existing_member)
                session_ops.commit()
                print(f"✅ Role updated to '{role}'.")
            return

        new_member = BudgetMember(
            budget_id=budget_id,
            user_id=user.id,
            role=role
        )
        session_ops.add(new_member)
        session_ops.commit()
        print(f"✅ User '{user_email}' (ID: {user.id}) successfully linked to budget '{budget.name}' (ID: {budget_id}) as '{role}'.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python link_users.py <user_email> <budget_id> [role]")
        print("Roles: owner, editor, viewer (default: editor)")
        sys.exit(1)

    email = sys.argv[1]
    bid = int(sys.argv[2])
    role_name = sys.argv[3] if len(sys.argv) > 3 else "editor"

    link_user_to_budget(email, bid, role_name)
