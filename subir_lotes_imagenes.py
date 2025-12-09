import subprocess
import os
import time

# AJUSTA ESTO si tu ruta es distinta
REPO_DIR = r"C:\Franco\Magic\tienda_web"

# Carpeta dentro del repo donde están las imágenes que se suben a la web
IMAGES_DIR = "images"

BATCH_SIZE = 20  # cantidad de archivos por lote
BRANCH = "main"
REMOTE = "origin"


def run(cmd):
    """
    Ejecuta un comando en el repo, mostrando la salida.
    No captura stdout porque acá no lo necesitamos, solo propagamos errores.
    """
    print(">>", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=REPO_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(f"[ERROR] Comando falló con código {result.returncode}")
        raise SystemExit(result.returncode)


def decode_git_escaped(path: str) -> str:
    """
    Git en Windows puede devolver rutas con escapes octales tipo:
      Supremac\\303\\255a  (que en UTF-8 es 'Supremacía')
    Esta función convierte esas secuencias \\xyz a bytes y luego a UTF-8 real.
    """
    b = bytearray()
    i = 0
    while i < len(path):
        if (
            path[i] == "\\"
            and i + 3 < len(path)
            and path[i + 1 : i + 4].isdigit()
        ):
            octal = path[i + 1 : i + 4]
            try:
                b.append(int(octal, 8))
                i += 4
                continue
            except ValueError:
                # Si por alguna razón no es octal válido, lo dejamos tal cual
                pass
        # Caracter normal
        b.append(ord(path[i]))
        i += 1

    return b.decode("utf-8", errors="replace")


def get_changed_files_in_dir(path_pattern: str):
    """
    Usa `git status --porcelain` para listar archivos nuevos/modificados
    dentro de una carpeta (por ejemplo 'images/').
    Forzamos core.quotepath=false y luego:
      - quitamos comillas sobrantes
      - decodificamos escapes octales
    """
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", path_pattern],
        cwd=REPO_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode != 0 or result.stdout is None:
        print("[ERROR] No se pudo obtener git status en get_changed_files_in_dir")
        print("STDERR:", result.stderr)
        raise SystemExit(result.returncode or 1)

    files = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Formato típico: "XY ruta/archivo" o "R  viejo -> nuevo"
        status = line[:2]
        path = line[3:].strip()

        # Si es un rename, nos quedamos con el NUEVO path después de '->'
        if "->" in path:
            path = path.split("->", 1)[1].strip()

        # Quitar espacios y comillas de ambos lados SIEMPRE
        path = path.strip().strip('"').strip()

        # Decodificar secuencias \xyz (octal) que usa git para caracteres no ASCII
        if "\\" in path:
            path = decode_git_escaped(path)

        if path:
            files.append(path)

    return files


def file_has_changes(path: str) -> bool:
    """Devuelve True si el archivo tiene cambios (nuevo o modificado)."""
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", path],
        cwd=REPO_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode != 0 or result.stdout is None:
        print(f"[ERROR] No se pudo obtener git status para {path}")
        print("STDERR:", result.stderr)
        raise SystemExit(result.returncode or 1)
    return bool(result.stdout.strip())


def main():
    print(f"[INFO] Repo dir: {REPO_DIR}")
    print(f"[INFO] Carpeta de imágenes: {IMAGES_DIR}")
    os.chdir(REPO_DIR)

    # 1) Verificar que estamos en la rama esperada
    branch_proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    current_branch = (branch_proc.stdout or "").strip()
    print(f"[INFO] Rama actual: {current_branch}")
    if current_branch != BRANCH:
        print(f"[WARN] No estás en la rama {BRANCH}. Estás en {current_branch}.")

    # 2) Archivos con cambios en la carpeta de imágenes
    image_pattern = IMAGES_DIR + "/"  # ej: "images/"
    changed_images = get_changed_files_in_dir(image_pattern)

    # 3) Opcional: incluir tienda_magic.html si tiene cambios
    extra_files = []
    if file_has_changes("tienda_magic.html"):
        extra_files.append("tienda_magic.html")

    all_files = extra_files + changed_images

    if not all_files:
        print("[INFO] No hay archivos nuevos/modificados en imágenes ni en tienda_magic.html")
        return

    print(f"[INFO] Total de archivos con cambios: {len(all_files)}")

    # 4) Procesar en lotes
    batch_num = 0
    for i in range(0, len(all_files), BATCH_SIZE):
        batch_num += 1
        batch = all_files[i: i + BATCH_SIZE]
        print(f"\n======================================")
        print(f"[INFO] Lote {batch_num}: {len(batch)} archivos")
        print("======================================")
        for f in batch:
            print("   -", f)

        # git add de este lote
        run(["git", "add"] + batch)

        # Verificar que realmente haya algo que commitear
        status_check = subprocess.run(
            ["git", "-c", "core.quotepath=false", "status", "--porcelain"],
            cwd=REPO_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if status_check.returncode != 0 or status_check.stdout is None:
            print("[ERROR] No se pudo obtener git status después de git add")
            print("STDERR:", status_check.stderr)
            raise SystemExit(status_check.returncode or 1)

        if not status_check.stdout.strip():
            print("[INFO] Después del add no hay cambios que commitear. Se salta este lote.")
            continue

        # Commit
        msg = f"Add images batch {batch_num}"
        run(["git", "commit", "-m", msg])

        # Push
        run(["git", "push", REMOTE, BRANCH])

        # Pausa entre lotes para no matar el pipeline
        time.sleep(600)  # 600 segundos = 10 minutos

        print("Program resumed after 10 minutes.")

    print("\n[OK] Todos los lotes procesados y subidos.")


if __name__ == "__main__":
    main()
