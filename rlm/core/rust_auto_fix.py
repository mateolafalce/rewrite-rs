"""
Sistema de auto-corrección para código Rust generado.
Permite al modelo iterar sobre errores de compilación y corregirlos automáticamente.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple


def get_project_structure(project_dir: str) -> str:
    """
    Obtiene la estructura del proyecto Rust.
    
    Args:
        project_dir: Directorio del proyecto
        
    Returns:
        String con la estructura del proyecto
    """
    structure = []
    project_path = Path(project_dir)
    
    structure.append(f"Proyecto: {project_path.name}")
    structure.append("=" * 60)
    
    # Listar archivos importantes
    for root, dirs, files in os.walk(project_dir):
        # Ignorar target y .git
        dirs[:] = [d for d in dirs if d not in ['target', '.git', 'node_modules']]
        
        level = root.replace(str(project_dir), '').count(os.sep)
        indent = ' ' * 2 * level
        structure.append(f'{indent}{os.path.basename(root)}/')
        
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            structure.append(f'{subindent}{file}')
    
    return '\n'.join(structure)


def read_project_files(project_dir: str) -> Dict[str, str]:
    """
    Lee todos los archivos relevantes del proyecto.
    
    Args:
        project_dir: Directorio del proyecto
        
    Returns:
        Diccionario con {ruta_relativa: contenido}
    """
    files_content = {}
    project_path = Path(project_dir)
    
    # Extensiones relevantes
    relevant_extensions = ['.rs', '.toml', '.md']
    
    for root, dirs, files in os.walk(project_dir):
        # Ignorar target y .git
        dirs[:] = [d for d in dirs if d not in ['target', '.git', 'node_modules']]
        
        for file in files:
            if any(file.endswith(ext) for ext in relevant_extensions):
                file_path = Path(root) / file
                relative_path = file_path.relative_to(project_path)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        files_content[str(relative_path)] = f.read()
                except Exception as e:
                    files_content[str(relative_path)] = f"Error leyendo archivo: {e}"
    
    return files_content


def parse_cargo_errors(cargo_output: str) -> List[Dict[str, str]]:
    """
    Parsea los errores de cargo build.
    
    Args:
        cargo_output: Output de cargo build
        
    Returns:
        Lista de diccionarios con información de errores
    """
    errors = []
    
    # Patrón para errores de compilación
    error_pattern = r'error(?:\[E\d+\])?: (.+?)\n\s+--\> (.+?):(\d+):(\d+)'
    matches = re.finditer(error_pattern, cargo_output, re.MULTILINE)
    
    for match in matches:
        errors.append({
            'message': match.group(1).strip(),
            'file': match.group(2).strip(),
            'line': int(match.group(3)),
            'column': int(match.group(4)),
            'full_context': match.group(0)
        })
    
    # También capturar el contexto completo de cada error
    error_blocks = re.split(r'\n(?=error)', cargo_output)
    
    return errors, error_blocks


def write_file_content(project_dir: str, relative_path: str, content: str) -> bool:
    """
    Escribe contenido en un archivo del proyecto.
    
    Args:
        project_dir: Directorio del proyecto
        relative_path: Ruta relativa del archivo
        content: Contenido a escribir
        
    Returns:
        True si se escribió exitosamente
    """
    try:
        file_path = Path(project_dir) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return True
    except Exception as e:
        print(f"Error escribiendo {relative_path}: {e}")
        return False


def extract_file_modifications(response: str) -> Dict[str, str]:
    """
    Extrae modificaciones de archivos de la respuesta del modelo.
    
    Busca patrones como:
    FILE: src/main.rs
    ```rust
    código...
    ```
    
    O simplemente bloques de código con nombres de archivo.
    
    Args:
        response: Respuesta del modelo
        
    Returns:
        Diccionario {ruta_archivo: contenido}
    """
    modifications = {}
    
    # Patrón 1: FILE: ruta seguido de bloque de código
    pattern1 = r'FILE:\s*([^\n]+)\s*\n```(?:rust|toml)?\s*\n(.*?)```'
    matches = re.finditer(pattern1, response, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        file_path = match.group(1).strip()
        content = match.group(2).strip()
        modifications[file_path] = content
    
    # Patrón 2: Menciones explícitas de archivos antes de bloques de código
    pattern2 = r'(?:src/main\.rs|Cargo\.toml|src/lib\.rs).*?\n```(?:rust|toml)?\s*\n(.*?)```'
    matches = re.finditer(pattern2, response, re.DOTALL)
    
    for match in matches:
        # Intentar extraer el nombre del archivo del contexto
        context = match.group(0)[:100]
        if 'main.rs' in context:
            modifications['src/main.rs'] = match.group(1).strip()
        elif 'Cargo.toml' in context:
            modifications['Cargo.toml'] = match.group(1).strip()
        elif 'lib.rs' in context:
            modifications['src/lib.rs'] = match.group(1).strip()
    
    # Patrón 3: Bloques de código Rust (asumir main.rs si no hay otro archivo)
    if not modifications:
        rust_pattern = r'```rust\s*\n(.*?)```'
        matches = re.findall(rust_pattern, response, re.DOTALL)
        if matches:
            # Tomar el bloque más largo
            longest = max(matches, key=len)
            modifications['src/main.rs'] = longest.strip()
    
    # Patrón 4: Bloques de TOML
    toml_pattern = r'```toml\s*\n(.*?)```'
    matches = re.findall(toml_pattern, response, re.DOTALL)
    if matches:
        modifications['Cargo.toml'] = matches[0].strip()
    
    return modifications


def build_auto_fix_prompt(
    project_dir: str,
    cargo_output: str,
    iteration: int,
    max_iterations: int = 5
) -> str:
    """
    Construye un prompt para que el modelo corrija errores de compilación.
    
    Args:
        project_dir: Directorio del proyecto
        cargo_output: Output del error de cargo
        iteration: Número de iteración actual
        max_iterations: Máximo de iteraciones permitidas
        
    Returns:
        Prompt para el modelo
    """
    # Leer archivos del proyecto
    files = read_project_files(project_dir)
    structure = get_project_structure(project_dir)
    
    prompt = f"""
RUST AUTO-FIX - Iteración {iteration}/{max_iterations}

Eres un experto en Rust. El código que generaste tiene errores de compilación.
Tu tarea es CORREGIR estos errores y proporcionar los archivos actualizados.

ESTRUCTURA DEL PROYECTO:
{structure}

ARCHIVOS ACTUALES:
"""
    
    for file_path, content in files.items():
        prompt += f"\n{'='*60}\nFILE: {file_path}\n{'='*60}\n{content}\n"
    
    prompt += f"""

{'='*60}
ERRORES DE COMPILACIÓN:
{'='*60}
{cargo_output}

{'='*60}
INSTRUCCIONES:
{'='*60}
1. Analiza los errores de compilación cuidadosamente
2. Identifica QUÉ archivos necesitan ser modificados
3. Proporciona el contenido COMPLETO y CORREGIDO de cada archivo que necesite cambios
4. Usa el siguiente formato para cada archivo:

FILE: ruta/del/archivo.rs
```rust
// Contenido completo corregido del archivo
```

FILE: Cargo.toml
```toml
# Contenido completo corregido
```

IMPORTANTE:
- Proporciona el contenido COMPLETO de cada archivo, no solo los cambios
- Asegúrate de que el código compile correctamente
- Si el error menciona dependencias faltantes, actualiza Cargo.toml
- Si el error es sobre sintaxis de Rust 2024, usa la sintaxis correcta
- NO uses características deprecadas
- Verifica que todas las importaciones sean correctas

ERRORES COMUNES A EVITAR:
- `gen` es una palabra reservada en Rust 2024, usa `random()` en su lugar
- Verifica que las dependencias en Cargo.toml estén correctamente especificadas
- Usa `ncurses` en lugar de `pancurses` si es necesario
- Asegúrate de que las versiones de las dependencias sean compatibles

Proporciona SOLO los archivos que necesitan ser modificados con su contenido completo.
"""
    
    return prompt


def auto_fix_rust_project(
    rlm,
    project_dir: str,
    max_iterations: int = 5,
    verbose: bool = True
) -> Tuple[bool, str, int]:
    """
    Intenta compilar y auto-corregir un proyecto Rust iterativamente.
    
    Args:
        rlm: Instancia de RLM para hacer queries
        project_dir: Directorio del proyecto Rust
        max_iterations: Máximo número de intentos de corrección
        verbose: Si True, muestra información detallada
        
    Returns:
        Tupla (éxito, último_output, iteraciones_usadas)
    """
    from .rust_utils import run_cargo_build
    
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        if verbose:
            print(f"\n{'='*70}")
            print(f"🔧 Intento de compilación #{iteration}/{max_iterations}")
            print(f"{'='*70}\n")
        
        # Intentar compilar
        success, output = run_cargo_build(project_dir)
        
        if success:
            if verbose:
                print(f"\n{'='*70}")
                print("✅ ¡Compilación exitosa!")
                print(f"{'='*70}\n")
            return True, output, iteration
        
        if verbose:
            print(f"\n{'='*70}")
            print(f"❌ Error en compilación (intento {iteration}/{max_iterations})")
            print(f"{'='*70}\n")
        
        # Si no es el último intento, pedir al modelo que corrija
        if iteration < max_iterations:
            if verbose:
                print("🤖 Solicitando correcciones al modelo...\n")
            
            # Construir prompt de corrección
            fix_prompt = build_auto_fix_prompt(project_dir, output, iteration, max_iterations)
            
            # Pedir al modelo que corrija
            try:
                result = rlm.completion(prompt=fix_prompt, root_prompt="Fix Rust compilation errors")
                response_text = result.response if hasattr(result, 'response') else str(result)
                
                if verbose:
                    print(f"\n{'='*70}")
                    print("📝 Respuesta del modelo:")
                    print(f"{'='*70}")
                    print(response_text[:500] + "..." if len(response_text) > 500 else response_text)
                    print(f"{'='*70}\n")
                
                # Extraer modificaciones de archivos
                modifications = extract_file_modifications(response_text)
                
                if not modifications:
                    if verbose:
                        print("⚠️  No se pudieron extraer modificaciones de la respuesta del modelo")
                    continue
                
                # Aplicar modificaciones
                if verbose:
                    print(f"📝 Aplicando {len(modifications)} modificaciones...\n")
                
                for file_path, content in modifications.items():
                    if write_file_content(project_dir, file_path, content):
                        if verbose:
                            print(f"  ✓ Actualizado: {file_path}")
                    else:
                        if verbose:
                            print(f"  ✗ Error actualizando: {file_path}")
                
                print()
                
            except Exception as e:
                if verbose:
                    print(f"❌ Error al solicitar correcciones: {e}\n")
                continue
    
    # Si llegamos aquí, no se pudo compilar después de max_iterations
    if verbose:
        print(f"\n{'='*70}")
        print(f"❌ No se pudo compilar después de {max_iterations} intentos")
        print(f"{'='*70}\n")
    
    return False, output, iteration
