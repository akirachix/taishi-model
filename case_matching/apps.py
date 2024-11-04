from django.apps import AppConfig


class CasesMatchingConfig(AppConfig):
   
    name = "case_matching"

def ready(self):
        try:
            # Full import path to avoid any potential import errors
            import case_matching.signals  
            print("Case matching signals imported successfully")
        except ImportError as e:
            print(f"Error importing signals: {e}")
