import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app import main
from app.models import Department, DepartmentCurator
from app.schemas import DepartmentCreate
from test_audit_fixes import env

def test_create_department_by_name_only(env):
    result = main.create_department(DepartmentCreate(name='  Учебный отдел  '), env.admin, env.db)
    item = env.db.get(Department, result['id'])
    assert item.name == 'Учебный отдел'
    assert item.code and item.is_active
    assert item.curators == []

def test_duplicate_name_rejected(env):
    payload = DepartmentCreate(name='Учебный отдел')
    main.create_department(payload, env.admin, env.db)
    with pytest.raises(HTTPException) as error:
        main.create_department(payload, env.admin, env.db)
    assert error.value.status_code == 409

def test_reactivate_preserves_old_identifier_and_curators(env):
    item = Department(code='OLD', name='Учебный отдел', is_active=False)
    item.curators = [DepartmentCurator(full_name='Иванова И. И.')]
    env.db.add(item); env.db.commit()
    result = main.create_department(DepartmentCreate(name=item.name), env.admin, env.db)
    assert result['id'] == item.id and item.code == 'OLD'
    assert item.is_active and len(item.curators) == 1

def test_empty_department_name_rejected():
    with pytest.raises(ValidationError):
        DepartmentCreate(name='  ')
