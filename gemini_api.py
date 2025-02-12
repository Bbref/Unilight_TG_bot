# gemini_api.py (отдельный модуль для работы с Gemini API)

import google.generativeai as genai
from docx import Document

class GeminiAPI:
    def __init__(self, api_key, system_prompt_file="system_prompt.txt", instructions_file="Все Инструкции для инженеров технической поддержки (формат).md"):
        self.api_key = api_key
        self.system_instruction = self._load_text_file(system_prompt_file)
        self.instructions_text = self._load_md_file(instructions_file)
        self.model = self._initialize_model()


    def _load_text_file(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            print(f"Файл {filepath} загружен.")
            return content
        except FileNotFoundError:
            print(f"Файл {filepath} не найден. Будет использован пустой промпт.")
            return ""
        except Exception as e:
            print(f"Ошибка при чтении файла {filepath}: {e}")
            return ""

    def _load_docx_file(self, filepath):
        try:
            doc = Document(filepath)
            content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            print(f"Файл {filepath} загружен.")
            return content
        except FileNotFoundError:
            print(f"Файл {filepath} не найден. Будут использованы пустые инструкции.")
            return ""
        except Exception as e:
            print(f"Ошибка при чтении файла {filepath}: {e}")
            return ""

    def _load_md_file(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            print(f"Файл {filepath} загружен.")
            return content
        except FileNotFoundError:
            print(f"Файл {filepath} не найден. Будет использован пустой промпт.")
            return ""
        except Exception as e:
            print(f"Ошибка при чтении файла {filepath}: {e}")
            return ""


    def _initialize_model(self):
        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=self.system_instruction
            )
            print("Модель Gemini инициализирована.")
            return model
        except Exception as e:
            print(f"Ошибка при инициализации модели: {e}")
            return None

    async def get_response(self, user_input):
        if not self.model:
            return "Ошибка: Модель Gemini не инициализирована."

        try:
            full_prompt = f"{self.instructions_text}\n\nВопрос: {user_input}\nОтвет:"  # Инструкции + вопрос
            response = self.model.generate_content(full_prompt)  # Системный промпт уже в модели

            if response and response.text:
                return response.text
            else:
                return "Не удалось найти ответ на ваш вопрос."

        except Exception as e:
            return f"Ошибка при обработке запроса: {str(e)}"