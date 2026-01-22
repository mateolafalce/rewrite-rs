"""
Utilidades para trabajar con código Rust generado por el modelo.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def extract_rust_code(response: str) -> Optional[str]:
    """
    Extrae código Rust de la respuesta del modelo.
    
    Busca bloques de código marcados con ```rust o ```
    También busca en el texto completo si no encuentra bloques de código.
    Ignora ejemplos pequeños como "Hello, world!" y prioriza código real.
    Maneja respuestas formateadas del RLM con caracteres de box-drawing.
    
    Args:
        response: La respuesta completa del modelo
        
    Returns:
        El código Rust extraído o None si no se encuentra
    """
    MIN_CODE_LENGTH = 100  # Mínimo de caracteres para considerar código real
    
    # Patrones que indican que es un ejemplo/placeholder, no código real
    PLACEHOLDER_PATTERNS = [
        r'\[YOUR.*?CODE.*?HERE\]',
        r'\[COMPLETE.*?CODE\]',
        r'\[INCLUDE.*?ALL\]',
        r'println!\("Hello, world!"\)',
        r'println!\("Hello world"\)',
        r'// Your converted.*code here',
        r'// Example',
        r'// Placeholder',
    ]
    
    def is_placeholder_code(code: str) -> bool:
        """Detecta si el código es un placeholder o ejemplo genérico."""
        code_upper = code.upper()
        
        # Verificar patrones de placeholder
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return True
        
        # Si contiene palabras como PLACEHOLDER, EXAMPLE, YOUR CODE
        if any(word in code_upper for word in ['[YOUR', '[COMPLETE', '[INCLUDE', 'PLACEHOLDER']):
            return True
        
        # Si es muy corto y solo tiene println! o print
        if len(code.strip()) < MIN_CODE_LENGTH:
            if 'println!' in code and code.count('\n') < 10:
                return True
        
        return False
    
    def clean_rlm_formatted_response(text: str) -> str:
        """
        Limpia respuestas formateadas del RLM con caracteres de box-drawing.
        Esto incluye paneles como:
        ╭─ ★ Final Answer ──────╮
        │ contenido             │
        ╰───────────────────────╯
        """
        # Paso 1: Eliminar wrapper FINAL( ... )
        final_pattern = r'FINAL\s*\(\s*(.*?)\s*\)\s*$'
        final_match = re.search(final_pattern, text, re.DOTALL | re.IGNORECASE)
        if final_match:
            text = final_match.group(1)
        
        # Paso 2: Extraer contenido de paneles del RLM
        # Buscar secciones entre paneles (╭...╮ y ╰...╯)
        panel_pattern = r'╭[─┬┴┼├┤┌┐└┘╭╮╯╰◇★▸\s\w\(\).]+╮\n(.*?)╰[─┬┴┼├┤┌┐└┘╭╮╯╰\s]+╯'
        panel_matches = re.findall(panel_pattern, text, re.DOTALL)
        
        if panel_matches:
            # Combinar el contenido de todos los paneles
            panel_content = '\n'.join(panel_matches)
            text = panel_content + '\n' + text  # Agregar también el texto original
        
        # Paso 3: Eliminar caracteres de box-drawing al inicio/final de cada línea
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Eliminar │ y otros caracteres de box-drawing al inicio
            cleaned_line = re.sub(r'^[│├╰╭╮╯─┤┼┴┬┌┐└┘\s]*', '', line)
            # También eliminar al final de la línea
            cleaned_line = re.sub(r'[│├╰╭╮╯─┤┼┴┬┌┐└┘\s]*$', '', cleaned_line)
            if cleaned_line.strip():  # Solo agregar líneas no vacías
                cleaned_lines.append(cleaned_line)
        
        return '\n'.join(cleaned_lines)
    
    def extract_from_text(text: str) -> Optional[str]:
        """Intenta extraer código Rust del texto dado."""
        # Buscar bloques de código con ```rust
        rust_pattern = r'```rust\s*\n(.*?)```'
        matches = re.findall(rust_pattern, text, re.DOTALL)
        
        if matches:
            # Filtrar placeholders y bloques muy pequeños
            real_code = [
                m for m in matches 
                if len(m.strip()) > MIN_CODE_LENGTH and not is_placeholder_code(m)
            ]
            if real_code:
                return max(real_code, key=len).strip()
        
        # Buscar bloques de código genéricos ```
        generic_pattern = r'```\s*\n(.*?)```'
        matches = re.findall(generic_pattern, text, re.DOTALL)
        
        if matches:
            rust_blocks = []
            for code in matches:
                if any(keyword in code for keyword in ['fn ', 'let ', 'use ', 'impl ', 'struct ', 'enum ', 'mod ']):
                    if len(code.strip()) > MIN_CODE_LENGTH and not is_placeholder_code(code):
                        rust_blocks.append(code.strip())
            
            if rust_blocks:
                return max(rust_blocks, key=len)
        
        # Buscar código Rust sin marcadores de bloque
        # Patrón: desde "use" hasta el final del código (} después de main)
        use_to_end_pattern = r'(use\s+\w+(?:::\w+)*\s*;.*?fn\s+main\s*\([^)]*\)\s*\{.*?\n\s*\}\s*)(?:\n\n|\Z)'
        match = re.search(use_to_end_pattern, text, re.DOTALL)
        if match:
            potential_code = match.group(1).strip()
            if len(potential_code) > MIN_CODE_LENGTH and not is_placeholder_code(potential_code):
                return potential_code
        
        return None
    
    # Primero intentar con la respuesta original (por si ya está limpia)
    result = extract_from_text(response)
    if result:
        return result
    
    # Segundo intento: limpiar formato RLM y volver a intentar
    cleaned_response = clean_rlm_formatted_response(response)
    result = extract_from_text(cleaned_response)
    if result:
        return result
    
    # Tercer intento: buscar patrones más flexibles
    # Patrón 1: Buscar desde "use" hasta "endwin()" o final de función main
    full_code_pattern = r'(use\s+(?:pancurses|ncurses|std|rand).*?fn\s+main\s*\(.*?\).*?(?:endwin\(\);|println!\([^)]*\);[\s\n]*}[\s\n]*))'
    match = re.search(full_code_pattern, cleaned_response, re.DOTALL)
    
    if match:
        potential_code = match.group(1).strip()
        if len(potential_code) > MIN_CODE_LENGTH and not is_placeholder_code(potential_code):
            return potential_code
    
    # Patrón 2: Buscar cualquier bloque que empiece con "use" y tenga "fn main"
    code_start_pattern = r'(use\s+.*?fn\s+main.*?)(?=\n\n(?:[A-Z]|If\s+you|Note:|Cargo\.toml|Build\s+and\s+run:)|\Z)'
    match = re.search(code_start_pattern, cleaned_response, re.DOTALL)
    
    if match:
        potential_code = match.group(1).strip()
        if len(potential_code) > MIN_CODE_LENGTH and 'fn main' in potential_code and not is_placeholder_code(potential_code):
            return potential_code
    
    # Patrón 3: Buscar código que contenga "fn main" y esté después de imports
    flexible_pattern = r'(?:use\s+[^;]+;\s*)+(?:\n\s*)?(?:(?:const|static|struct|enum|type|fn|impl|trait|mod|pub)\s+[^{]+\{[^}]*\}\s*)*fn\s+main\s*\([^)]*\)\s*\{[\s\S]*?\n\}'
    match = re.search(flexible_pattern, cleaned_response)
    
    if match:
        potential_code = match.group(0).strip()
        if len(potential_code) > MIN_CODE_LENGTH and not is_placeholder_code(potential_code):
            return potential_code
    
    return None


def extract_cargo_dependencies(response: str) -> dict:
    """
    Extrae las dependencias de Cargo.toml mencionadas en la respuesta.
    
    Args:
        response: La respuesta completa del modelo
        
    Returns:
        Diccionario con las dependencias encontradas
    """
    dependencies = {}
    
    # Limpiar la respuesta
    lines = response.split('\n')
    cleaned_lines = []
    for line in lines:
        cleaned_line = re.sub(r'^[│├╰╭╮╯╰─┤┼┴┬┌┐└┘\s]+', '', line)
        cleaned_lines.append(cleaned_line)
    cleaned_response = '\n'.join(cleaned_lines)
    
    # Patrón 1: Buscar bloques de Cargo.toml dependencies
    cargo_toml_pattern = r'\[dependencies\]\s*\n((?:[\w\-]+ = [^\n]+\n?)+)'
    match = re.search(cargo_toml_pattern, cleaned_response)
    
    if match:
        dep_block = match.group(1)
        # Parsear cada línea de dependencia
        for line in dep_block.split('\n'):
            if '=' in line:
                parts = line.split('=', 1)
                dep_name = parts[0].strip()
                dep_value = parts[1].strip().strip('"')
                dependencies[dep_name] = dep_value
    
    # Patrón 2: Buscar menciones explícitas de dependencias (e.g., "- ncurses = \"5\"")
    dep_list_pattern = r'[-*]\s+([\w\-]+)\s*=\s*["\']([^"\']+)["\']'
    matches = re.findall(dep_list_pattern, cleaned_response)
    for dep_name, dep_value in matches:
        if dep_name not in dependencies:
            dependencies[dep_name] = dep_value
    
    # Patrón 3: Buscar en texto como "Cargo.toml dependencies (add to your project):"
    # seguido de lista de dependencias
    dep_section_pattern = r'Cargo\.toml dependencies.*?:\s*\n((?:[-*]\s+[\w\-]+ = [^\n]+\n?)+)'
    match = re.search(dep_section_pattern, cleaned_response, re.IGNORECASE)
    
    if match:
        dep_block = match.group(1)
        for line in dep_block.split('\n'):
            if '=' in line:
                # Extraer "nombre = valor" de líneas como "- ncurses = \"5\""
                dep_match = re.search(r'([\w\-]+)\s*=\s*["\']?([^"\']+)["\']?', line)
                if dep_match:
                    dep_name, dep_value = dep_match.groups()
                    if dep_name not in dependencies:
                        dependencies[dep_name] = dep_value.strip()
    
    return dependencies


def write_rust_file(code: str, output_path: str) -> bool:
    """
    Escribe código Rust en un archivo.
    
    Args:
        code: El código Rust a escribir
        output_path: Ruta donde guardar el archivo
        
    Returns:
        True si se escribió exitosamente, False en caso contrario
    """
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        print(f"✓ Código Rust guardado en: {output_path}")
        return True
    except Exception as e:
        print(f"✗ Error al escribir archivo Rust: {e}")
        return False


def setup_cargo_project(project_dir: str, binary_name: str = "main") -> bool:
    """
    Configura un proyecto Cargo básico si no existe.
    
    Args:
        project_dir: Directorio del proyecto Cargo
        binary_name: Nombre del binario a crear
        
    Returns:
        True si se configuró exitosamente, False en caso contrario
    """
    try:
        project_path = Path(project_dir)
        
        # Si ya existe Cargo.toml, no hacer nada
        if (project_path / "Cargo.toml").exists():
            return True
        
        # Crear directorio del proyecto
        project_path.mkdir(parents=True, exist_ok=True)
        
        # Crear Cargo.toml básico
        cargo_toml = f"""[package]
name = "{binary_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
"""
        
        with open(project_path / "Cargo.toml", 'w') as f:
            f.write(cargo_toml)
        
        # Crear directorio src
        (project_path / "src").mkdir(exist_ok=True)
        
        print(f"✓ Proyecto Cargo configurado en: {project_dir}")
        return True
    except Exception as e:
        print(f"✗ Error al configurar proyecto Cargo: {e}")
        return False


def update_cargo_dependencies(project_dir: str, dependencies: dict) -> bool:
    """
    Actualiza el Cargo.toml con las dependencias extraídas.
    
    Args:
        project_dir: Directorio del proyecto Cargo
        dependencies: Diccionario con las dependencias a agregar
        
    Returns:
        True si se actualizó exitosamente, False en caso contrario
    """
    if not dependencies:
        return True  # No hay nada que hacer
    
    try:
        cargo_toml_path = Path(project_dir) / "Cargo.toml"
        
        if not cargo_toml_path.exists():
            print(f"✗ No existe Cargo.toml en {project_dir}")
            return False
        
        # Leer el contenido actual
        with open(cargo_toml_path, 'r') as f:
            content = f.read()
        
        # Verificar si ya tiene una sección [dependencies]
        if '[dependencies]' in content:
            # Agregar las dependencias después de [dependencies]
            lines = content.split('\n')
            new_lines = []
            in_dependencies = False
            dependencies_added = False
            
            for line in lines:
                new_lines.append(line)
                
                if line.strip() == '[dependencies]' and not dependencies_added:
                    in_dependencies = True
                    # Agregar las nuevas dependencias
                    for dep_name, dep_value in dependencies.items():
                        # Verificar si la dependencia ya existe
                        if not any(dep_name in l for l in lines):
                            new_lines.append(f'{dep_name} = "{dep_value}"')
                    dependencies_added = True
                elif in_dependencies and line.strip().startswith('['):
                    in_dependencies = False
            
            content = '\n'.join(new_lines)
        else:
            # Agregar sección [dependencies] al final
            content += '\n[dependencies]\n'
            for dep_name, dep_value in dependencies.items():
                content += f'{dep_name} = "{dep_value}"\n'
        
        # Escribir el archivo actualizado
        with open(cargo_toml_path, 'w') as f:
            f.write(content)
        
        print(f"✓ Cargo.toml actualizado con {len(dependencies)} dependencias")
        for dep_name, dep_value in dependencies.items():
            print(f"  - {dep_name} = \"{dep_value}\"")
        
        return True
        
    except Exception as e:
        print(f"✗ Error al actualizar Cargo.toml: {e}")
        return False


def run_cargo_build(project_dir: str, release: bool = False) -> Tuple[bool, str]:
    """
    Ejecuta cargo build en el proyecto especificado.
    
    Args:
        project_dir: Directorio del proyecto Cargo
        release: Si True, compila en modo release
        
    Returns:
        Tupla (éxito, output) donde éxito es True si compiló correctamente
    """
    try:
        cmd = ["cargo", "build"]
        if release:
            cmd.append("--release")
        
        print(f"\n{'='*60}")
        print(f"Ejecutando: {' '.join(cmd)}")
        print(f"En directorio: {project_dir}")
        print(f"{'='*60}\n")
        
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120  # 2 minutos de timeout
        )
        
        output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        
        if result.returncode == 0:
            print("✓ Compilación exitosa!")
            print(output)
            return True, output
        else:
            print("✗ Error en la compilación:")
            print(output)
            return False, output
            
    except subprocess.TimeoutExpired:
        error_msg = "✗ Timeout: La compilación tardó más de 2 minutos"
        print(error_msg)
        return False, error_msg
    except FileNotFoundError:
        error_msg = "✗ Error: 'cargo' no está instalado o no está en el PATH"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"✗ Error inesperado al ejecutar cargo build: {e}"
        print(error_msg)
        return False, error_msg


def run_cargo_check(project_dir: str) -> Tuple[bool, str]:
    """
    Ejecuta cargo check en el proyecto especificado (más rápido que build).
    
    Args:
        project_dir: Directorio del proyecto Cargo
        
    Returns:
        Tupla (éxito, output) donde éxito es True si el check pasó
    """
    try:
        cmd = ["cargo", "check"]
        
        print(f"\n{'='*60}")
        print(f"Ejecutando: {' '.join(cmd)}")
        print(f"En directorio: {project_dir}")
        print(f"{'='*60}\n")
        
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        
        if result.returncode == 0:
            print("✓ Check exitoso!")
            print(output)
            return True, output
        else:
            print("✗ Error en el check:")
            print(output)
            return False, output
            
    except Exception as e:
        error_msg = f"✗ Error al ejecutar cargo check: {e}"
        print(error_msg)
        return False, error_msg


def process_c_to_rust_conversion(
    response: str,
    output_dir: str = "./rust_output",
    source_name: str = "main",
    run_build: bool = True,
    run_check_only: bool = False
) -> dict:
    """
    Procesa una respuesta de conversión de C a Rust.
    
    Extrae el código Rust, lo guarda en un archivo, configura un proyecto Cargo
    y opcionalmente ejecuta cargo build/check.
    
    Args:
        response: La respuesta del modelo con el código Rust
        output_dir: Directorio donde crear el proyecto Rust
        source_name: Nombre del archivo fuente (sin extensión)
        run_build: Si True, ejecuta cargo build
        run_check_only: Si True, solo ejecuta cargo check (más rápido)
        
    Returns:
        Diccionario con información sobre el proceso:
        {
            'success': bool,
            'rust_code': str o None,
            'file_path': str o None,
            'build_success': bool o None,
            'build_output': str o None
        }
    """
    result = {
        'success': False,
        'rust_code': None,
        'file_path': None,
        'build_success': None,
        'build_output': None
    }
    
    # Extraer código Rust
    rust_code = extract_rust_code(response)
    if not rust_code:
        print("✗ No se pudo extraer código Rust de la respuesta")
        return result
    
    result['rust_code'] = rust_code
    
    # Configurar proyecto Cargo
    if not setup_cargo_project(output_dir, source_name):
        return result
    
    # Extraer y actualizar dependencias
    dependencies = extract_cargo_dependencies(response)
    if dependencies:
        update_cargo_dependencies(output_dir, dependencies)
    
    # Escribir archivo Rust
    file_path = os.path.join(output_dir, "src", f"{source_name}.rs")
    if not write_rust_file(rust_code, file_path):
        return result
    
    result['file_path'] = file_path
    result['success'] = True
    
    # Ejecutar cargo check o build si se solicita
    if run_build or run_check_only:
        if run_check_only:
            build_success, build_output = run_cargo_check(output_dir)
        else:
            build_success, build_output = run_cargo_build(output_dir)
        
        result['build_success'] = build_success
        result['build_output'] = build_output
    
    return result
