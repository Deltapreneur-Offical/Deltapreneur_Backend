from app.core.database import engine
from app.entity.virtual_assistant.application_role_entity import ApplicationRole
from app.entity.virtual_assistant.virtual_assistant_entity import VirtualAssistantApplication
from app.entity.base import Base

Base.metadata.create_all(engine, tables=[VirtualAssistantApplication.__table__, ApplicationRole.__table__])
print("Tables created successfully")
