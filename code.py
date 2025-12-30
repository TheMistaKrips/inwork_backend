import os
import argparse
from pathlib import Path

def should_skip_directory(dir_name):
    """Проверяет, нужно ли пропускать директорию"""
    skip_dirs = {
        'node_modules', '.git', 'build', 'dist', 'coverage', 
        '.next', '.nuxt', '.cache', 'assets', 'static',
        'public', '.vscode', '.idea', '__pycache__', 'cache',
        'logs', 'temp', 'tmp', 'vendor', 'bin', 'obj'
    }
    return dir_name in skip_dirs or dir_name.startswith('.')

def should_skip_file(file_name):
    """Проверяет, нужно ли пропускать файл"""
    skip_files = {
        'package.json', 'package-lock.json', 'yarn.lock',
        'tsconfig.json', 'webpack.config.js', '.eslintrc.js',
        '.prettierrc', 'babel.config.js', 'next.config.js',
        'jest.config.js', 'vue.config.js', 'nuxt.config.js',
        '.gitignore', '.env', '.env.local', 'README.md'
    }
    return file_name in skip_files

def is_target_file(file_name):
    """Проверяет, является ли файл целевым (JS/JSX/TS/TSX и другие исходные файлы)"""
    target_extensions = {
        '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte',
        '.css', '.scss', '.less', '.html', '.htm', '.json',
        '.py', '.java', '.cpp', '.c', '.h', '.cs', '.php',
        '.rb', '.go', '.rs', '.swift', '.kt', '.dart'
    }
    return any(file_name.endswith(ext) for ext in target_extensions)

def get_file_category(file_extension):
    """Возвращает категорию файла для группировки"""
    categories = {
        '.js': 'JavaScript',
        '.jsx': 'React JSX',
        '.ts': 'TypeScript', 
        '.tsx': 'React TypeScript',
        '.vue': 'Vue',
        '.svelte': 'Svelte',
        '.py': 'Python',
        '.html': 'HTML',
        '.css': 'CSS',
        '.scss': 'SCSS',
        '.less': 'LESS',
        '.json': 'JSON',
        '.java': 'Java',
        '.cpp': 'C++',
        '.c': 'C',
        '.cs': 'C#',
        '.php': 'PHP',
        '.rb': 'Ruby',
        '.go': 'Go',
        '.rs': 'Rust',
        '.swift': 'Swift',
        '.kt': 'Kotlin',
        '.dart': 'Dart'
    }
    return categories.get(file_extension, 'Other')

def format_file_header(file_path, relative_path, category):
    """Форматирует заголовок файла"""
    header = []
    header.append("╔" + "═" * 78 + "╗")
    header.append(f"║ ФАЙЛ: {relative_path:<70} ║")
    header.append(f"║ КАТЕГОРИЯ: {category:<65} ║")
    header.append(f"║ ПОЛНЫЙ ПУТЬ: {file_path:<64} ║")
    header.append("╚" + "═" * 78 + "╝")
    return '\n'.join(header)

def format_file_footer():
    """Форматирует подвал файла"""
    return "\n" + "─" * 80 + "\n"

def collect_source_files(root_dir, output_file):
    """Рекурсивно собирает исходные файлы и записывает их в output_file"""
    
    root_path = Path(root_dir)
    files_by_category = {}
    total_files = 0
    
    print("🔍 Сканирую структуру проекта...")
    
    # Сначала собираем все файлы по категориям
    for root, dirs, files in os.walk(root_dir):
        # Удаляем директории, которые нужно пропустить
        dirs[:] = [d for d in dirs if not should_skip_directory(d)]
        
        for file in files:
            if should_skip_file(file):
                continue
                
            if is_target_file(file):
                file_path = Path(root) / file
                relative_path = file_path.relative_to(root_path)
                file_extension = file_path.suffix.lower()
                category = get_file_category(file_extension)
                
                if category not in files_by_category:
                    files_by_category[category] = []
                
                files_by_category[category].append((file_path, relative_path))
                total_files += 1
    
    print(f"📁 Найдено {total_files} файлов в {len(files_by_category)} категориях")
    
    # Записываем файлы в выходной файл, сгруппированные по категориям
    with open(output_file, 'w', encoding='utf-8') as out_f:
        # Заголовок документа
        out_f.write("=" * 80 + "\n")
        out_f.write(f"ИСХОДНЫЙ КОД ПРОЕКТА\n")
        out_f.write(f"Директория: {root_dir}\n")
        out_f.write(f"Всего файлов: {total_files}\n")
        out_f.write("=" * 80 + "\n\n")
        
        # Проходим по категориям в алфавитном порядке
        for category in sorted(files_by_category.keys()):
            files_in_category = files_by_category[category]
            
            # Заголовок категории
            out_f.write("\n" + "■" * 80 + "\n")
            out_f.write(f"КАТЕГОРИЯ: {category} ({len(files_in_category)} файлов)\n")
            out_f.write("■" * 80 + "\n\n")
            
            # Сортируем файлы по пути
            for file_path, relative_path in sorted(files_in_category, key=lambda x: str(x[1])):
                try:
                    # Записываем заголовок файла
                    out_f.write(format_file_header(str(file_path), str(relative_path), category))
                    out_f.write("\n\n")
                    
                    # Читаем и записываем содержимое файла
                    with open(file_path, 'r', encoding='utf-8') as in_f:
                        content = in_f.read().rstrip()  # Убираем лишние пробелы в конце
                        out_f.write(content)
                    
                    # Записываем подвал файла
                    out_f.write(format_file_footer())
                    
                    print(f"✅ Обработан: {relative_path}")
                    
                except UnicodeDecodeError:
                    try:
                        # Пробуем другую кодировку
                        with open(file_path, 'r', encoding='cp1251') as in_f:
                            content = in_f.read().rstrip()
                            out_f.write(content)
                        out_f.write(format_file_footer())
                        print(f"✅ Обработан (Windows-1251): {relative_path}")
                    except Exception as e:
                        out_f.write(f"// ⚠️ Ошибка чтения файла: {e}\n")
                        out_f.write(format_file_footer())
                        print(f"❌ Ошибка: {relative_path} - {e}")
                        
                except Exception as e:
                    out_f.write(f"// ⚠️ Ошибка чтения файла: {e}\n")
                    out_f.write(format_file_footer())
                    print(f"❌ Ошибка: {relative_path} - {e}")

def main():
    parser = argparse.ArgumentParser(
        description='📁 Сборщик исходного кода проекта - создает структурированный файл со всем кодом',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--input', '-i', default='.', 
                       help='Входная директория (по умолчанию текущая)')
    parser.add_argument('--output', '-o', default='project_code.txt',
                       help='Выходной файл (по умолчанию project_code.txt)')
    
    args = parser.parse_args()
    
    input_dir = os.path.abspath(args.input)
    output_file = args.output
    
    if not os.path.exists(input_dir):
        print(f"❌ Ошибка: Директория {input_dir} не существует!")
        return
    
    print("🚀 Запуск сборщика исходного кода...")
    print(f"📂 Исходная директория: {input_dir}")
    print(f"💾 Выходной файл: {output_file}")
    print("-" * 60)
    
    collect_source_files(input_dir, output_file)
    
    print("-" * 60)
    print(f"🎉 Сборка завершена успешно!")
    print(f"📄 Все файлы сохранены в: {output_file}")

if __name__ == "__main__":
    main()