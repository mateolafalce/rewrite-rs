from rlm import RLM
from rlm.logger import RLMLogger
from rlm.core.rust_utils import process_c_to_rust_conversion
from rlm.core.rust_auto_fix import auto_fix_rust_project
from rlm.utils.prompts import CODE_CONVERSION_INSTRUCTION
from dotenv import load_dotenv
import os

load_dotenv()

logger = RLMLogger(log_dir="./logs")

def main():
    with open("./snake/snake.c", "r") as f:
        context = f.read()

    rlm = RLM(
        backend="openai",
        backend_kwargs={
            "api_key": os.getenv("OPENAI_API_KEY"),
            "model_name": "gpt-5-nano"
        },
        environment_kwargs={},
        environment="local",
        max_depth=1,
        logger=logger,
        max_iterations=3,
        verbose=True,
    )

    query = "Re-write this code from C to rust"
    prompt = f"Context: {context}\n\nQuery: {query}\n\n{CODE_CONVERSION_INSTRUCTION}\n"
    
    result = rlm.completion(prompt=prompt, root_prompt=query)

    # Obtener el texto de respuesta del RLM
    response_text = result.response if hasattr(result, 'response') else str(result)
    
    # Debug: mostrar longitud de la respuesta
    print(f"\n{'='*60}")
    print(f"📋 Longitud de la respuesta del RLM: {len(response_text)} caracteres")
    print(f"{'='*60}\n")
    
    # Si la respuesta es muy corta o es un placeholder, buscar en otras partes
    if len(response_text) < 100 or response_text.strip().lower() in ['your final answer here', 'final answer']:
        print("⚠️  Respuesta muy corta, buscando en otras fuentes...")
        
        # Intentar obtener el texto completo del resultado
        full_text = getattr(result, 'prompt', None)
        if full_text is None:
            full_text = str(result)
        
        if isinstance(full_text, str) and len(full_text) > len(response_text):
            response_text = full_text
            print(f"✓ Encontrado texto más largo: {len(response_text)} caracteres")
    
    # Debug: mostrar primeros caracteres de la respuesta
    print(f"\n📜 Primeros 500 caracteres de la respuesta:")
    print("-" * 60)
    print(response_text[:500])
    print("-" * 60 + "\n")
    
    # Procesar la conversión inicial (sin build automático)
    conversion_result = process_c_to_rust_conversion(
        response=response_text,
        output_dir="./vibora",
        source_name="main",
        run_build=False,  # No compilar aún, lo haremos con auto-fix
        run_check_only=False
    )
    
    # Si no se pudo extraer código Rust, intentar con str(result) completo
    if not conversion_result.get('rust_code'):
        print("⚠️  No se encontró código Rust en response, intentando con str(result)...")
        full_result_str = str(result)
        if '```rust' in full_result_str or 'use ' in full_result_str:
            conversion_result = process_c_to_rust_conversion(
                response=full_result_str,
                output_dir="./vibora",
                source_name="main",
                run_build=False,
                run_check_only=False
            )
    
    success, output, iterations = auto_fix_rust_project(
        rlm=rlm,
        project_dir="./vibora",
        max_iterations=5,
        verbose=True
    )
    
    return result
    

if __name__ == "__main__":
    main()