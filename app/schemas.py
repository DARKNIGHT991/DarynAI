from pydantic import BaseModel


class UserRegister(BaseModel):
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class GoogleLogin(BaseModel):
    credential: str


class HistoryRequest(BaseModel):
    email: str


class ChatRequest(BaseModel):
    text: str
    email: str
    mode: str = "chat"
    chat_id: int | None = None
    file_name: str | None = None
    file_type: str | None = None
    file_data: str | None = None


class ProfileUpdate(BaseModel):
    email: str
    new_username: str


class PlanUpgrade(BaseModel):
    email: str
    plan: str
    tx_id: str = ""


class AdminPlanChange(BaseModel):
    admin_email: str
    target_email: str
    plan: str
    days: int = 30


class ChatCreate(BaseModel):
    email: str
    title: str = "Новый чат"


class ChatRename(BaseModel):
    email: str
    chat_id: int
    title: str


class ChatDelete(BaseModel):
    email: str
    chat_id: int


class ChatHistoryRequest(BaseModel):
    email: str
    chat_id: int
