from pydantic_settings import BaseSettings
from pydantic import EmailStr


class Settings(BaseSettings):
    app_name: str = "LLM Analysis Quiz Solver"

    # Must match what you put in the Google Form
    expected_secret: str
    student_email: EmailStr

    # LLM config
    openai_api_key: str
    llm_model: str = "gpt-4o-mini"  # or any supported OpenAI model

    max_quiz_duration_secs: int = 170  # Slightly below 3 minutes

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
