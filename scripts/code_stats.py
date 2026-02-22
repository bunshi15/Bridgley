import os
import sys
import argparse
from collections import defaultdict
import re


EXTENSIONS = ['.py', '.spec', '.java', '.js', '.html', '.css', '.c', '.cpp', '.rs', '.db', '.md']
EXCLUDED_DIRS = ['venv', '.venv', '.venv313', 'node_modules', '.git', '__pycache__', 'build', 'dist', 'temp', 'obsolete', "db"]


def count_lines(file_path):
    """Подсчет строк кода, пустых строк и комментариев."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            total_lines = len(lines)
            empty_lines = sum(1 for line in lines if line.strip() == '')
            comment_lines = 0

            # Проверка на комментарии зависит от типа файла
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.py']:
                comment_lines = sum(1 for line in lines if line.strip().startswith('#'))
            elif ext in ['.java', '.js', '.c', '.cpp', '.cs', '.rs']:
                # Однострочные комментарии
                comment_lines = sum(1 for line in lines if line.strip().startswith('//'))
                # Подсчет многострочных комментариев (упрощённый вариант)
                in_comment = False
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('/*') and '*/' in stripped:
                        comment_lines += 1
                    elif stripped.startswith('/*'):
                        in_comment = True
                        comment_lines += 1
                    elif '*/' in stripped and in_comment:
                        in_comment = False
                        comment_lines += 1
                    elif in_comment:
                        comment_lines += 1

            return {
                'total': total_lines,
                'code': total_lines - empty_lines - comment_lines,
                'comments': comment_lines,
                'empty': empty_lines
            }
    except Exception as e:
        print(f"Ошибка при подсчете {file_path}: {e}")
        return {'total': 0, 'code': 0, 'comments': 0, 'empty': 0}


def scan_directory(directory, extensions=None, excluded_dirs=None, excluded_file_patterns=None):
    """Сканировать директорию и получить статистику по файлам."""
    if extensions is None:
        extensions = EXTENSIONS

    if excluded_dirs is None:
        excluded_dirs = EXCLUDED_DIRS

    if excluded_file_patterns is None:
        excluded_file_patterns = []

    results = defaultdict(lambda: {'files': 0, 'total': 0, 'code': 0, 'comments': 0, 'empty': 0})
    file_count = 0
    skipped_count = 0

    for root, dirs, files in os.walk(directory):
        # Пропустить исключенные директории
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            # Проверяем, соответствует ли файл шаблонам исключения
            should_skip = False
            for pattern in excluded_file_patterns:
                if pattern.match(file):
                    should_skip = True
                    skipped_count += 1
                    break

            if should_skip:
                continue

            ext = os.path.splitext(file)[1].lower()
            if ext in extensions:
                file_path = os.path.join(root, file)
                file_count += 1
                if file_count % 100 == 0:
                    print(f"Обработано файлов: {file_count}, пропущено: {skipped_count}", end='\r')

                stats = count_lines(file_path)
                results[ext]['files'] += 1
                results[ext]['total'] += stats['total']
                results[ext]['code'] += stats['code']
                results[ext]['comments'] += stats['comments']
                results[ext]['empty'] += stats['empty']

    # Выводим итоговую информацию о пропущенных файлах
    print(f"\nВсего обработано файлов: {file_count}, пропущено: {skipped_count}")
    return results


def print_results(results):
    """Вывести результаты в читаемом формате."""
    print("\nРезультаты анализа кодовой базы:")
    print("-" * 80)
    print(
        f"{'Расширение':<10} {'Файлы':<10} {'Всего строк':<15} {'Строк кода':<15} {'Комментарии':<15} {'Пустые строки':<15}")
    print("-" * 80)

    total_files = 0
    total_lines = 0
    total_code = 0
    total_comments = 0
    total_empty = 0

    for ext, stats in sorted(results.items()):
        print(
            f"{ext:<10} {stats['files']:<10} {stats['total']:<15} {stats['code']:<15} {stats['comments']:<15} {stats['empty']:<15}")
        total_files += stats['files']
        total_lines += stats['total']
        total_code += stats['code']
        total_comments += stats['comments']
        total_empty += stats['empty']

    print("-" * 80)
    print(f"{'ИТОГО':<10} {total_files:<10} {total_lines:<15} {total_code:<15} {total_comments:<15} {total_empty:<15}")
    print("-" * 80)


if __name__ == "__main__":
    # Создаем парсер аргументов командной строки
    parser = argparse.ArgumentParser(description='Подсчет строк кода в проекте')
    parser.add_argument('directory', nargs='?', default=None,
                        help='Директория для анализа (по умолчанию: уровень выше скрипта)')
    parser.add_argument('-e', '--extensions', nargs='+',
                        help='Расширения файлов для анализа (например: py java js)')
    parser.add_argument('--exclude-dirs', nargs='+',
                        help='Директории для исключения (например: venv node_modules)')
    parser.add_argument('--exclude-files', nargs='+',
                        help='Шаблоны файлов для исключения (например: *.min.js test_*.py)')

    args = parser.parse_args()

    # Определяем директорию для анализа
    if args.directory:
        directory = args.directory
    else:
        # Корневой путь на уровень выше, чем скрипт
        directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # Определяем расширения файлов
    extensions = None
    if args.extensions:
        extensions = [f".{ext}" if not ext.startswith('.') else ext for ext in args.extensions]

    # Определяем исключаемые директории
    excluded_dirs = EXCLUDED_DIRS
    if args.exclude_dirs:
        excluded_dirs.extend(args.exclude_dirs)

    # Компилируем регулярные выражения для исключаемых файлов
    excluded_file_patterns = []
    if args.exclude_files:
        for pattern in args.exclude_files:
            # Преобразуем шаблоны типа *.py в регулярные выражения
            regex_pattern = pattern.replace('.', '\\.').replace('*', '.*')
            excluded_file_patterns.append(re.compile(regex_pattern))

    print(f"Анализ директории: {os.path.abspath(directory)}")
    print(f"Скрипт расположен в: {os.path.dirname(os.path.abspath(__file__))}")
    if extensions:
        print(f"Расширения файлов: {', '.join(extensions)}")
    if excluded_dirs:
        print(f"Исключаемые директории: {', '.join(excluded_dirs)}")
    if excluded_file_patterns:
        print(f"Исключаемые шаблоны файлов: {', '.join(args.exclude_files)}")

    results = scan_directory(directory, extensions, excluded_dirs, excluded_file_patterns)
    print_results(results)