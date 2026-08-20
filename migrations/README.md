# 데이터베이스 마이그레이션

Alembic을 사용해 PostgreSQL 스키마 변경 이력을 관리합니다.

```powershell
alembic upgrade head
alembic revision --autogenerate -m "변경 내용"
alembic downgrade -1
```

모델을 추가한 뒤에는 `app.db.base.Base`의 metadata에 모델이 등록됐는지 확인해야 합니다.
