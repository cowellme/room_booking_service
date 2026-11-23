"""Use the canonical department directory from Pyrus."""

from alembic import op
import sqlalchemy as sa

revision = "0027_pyrus_departments"
down_revision = "0026_booking_event_format"
branch_labels = None
depends_on = None

DEPARTMENTS = (
    "Административно-организационный отдел",
    "Центр «Цифровая школа госуправления»",
    "Центр «Школа андрагогики и образовательного дизайна»",
    "Научно-образовательный центр развития образования",
    'Научно-исследовательская лаборатория "Диагностика и оценка руководителей"',
    "Центр разработок и аналитики",
    "Кафедра психологии личности в системах управления",
    "Центр оценки руководителей и управленческих команд",
    "Центр современных кадровых технологий",
    "Центр развития регионов",
    "Центр специальных программ и проектов",
    "Центр программ подготовки руководителей высшего звена",
    "Центр развития лидерских и управленческих компетенций",
    "Центр управления групповой коммуникацией",
    "Центр внедрения клиентоцентричного подхода",
    "Центр развития международных проектов",
    "Центр управления программами и проектами",
    "Отдел по работе и развитию персонала",
    "Центр развития конкурентной политики и государственного заказа",
    "Центр современных коммуникаций",
    "Центр экспертно-консультационного сопровождения местного самоуправления",
    "Центр карьерного сопровождения",
    "Федеральный центр подготовки управленческих кадров",
    "Центр комплексной оценки компетенций",
    "Центр специальной подготовки",
    "Отдел правового сопровождения",
    "Экспертно-аналитический центр государственной и муниципальной службы",
    "Центр политических коммуникаций и компетенций",
    "Центр научно-исследовательского и экспертного сопровождения проектов, содействующего достижению национальных целей развития имени Петра Аркадьевича Столыпина",
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE departments SET is_active = false"))
    for position, name in enumerate(DEPARTMENTS, start=1):
        existing_id = connection.execute(
            sa.text("SELECT id FROM departments WHERE lower(trim(name)) = lower(trim(:name)) ORDER BY id LIMIT 1"),
            {"name": name},
        ).scalar()
        if existing_id is not None:
            connection.execute(
                sa.text("UPDATE departments SET name = :name, is_active = true WHERE id = :id"),
                {"id": existing_id, "name": name},
            )
            continue
        code = f"PYRUS-{position:03d}"
        while connection.execute(sa.text("SELECT 1 FROM departments WHERE code = :code"), {"code": code}).first():
            code += "X"
        connection.execute(
            sa.text("INSERT INTO departments (code, name, is_active, created_at) VALUES (:code, :name, true, CURRENT_TIMESTAMP)"),
            {"code": code, "name": name},
        )


def downgrade() -> None:
    # Do not delete rows referenced by historical bookings.
    op.execute("UPDATE departments SET is_active = true")
