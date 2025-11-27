import os
import string
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox
import openpyxl
import re


def clean_filename(filename):
    """
    Удаляет знаки препинания из имени файла (без расширения),
    но сохраняет суффиксы вида _1, -2, _10 и преобразует их в (1), (2) и т.д.
    """
    name, ext = os.path.splitext(filename)
    ext = ext.lower()

    # Паттерн для поиска суффикса вида _123 или -456 в конце строки
    suffix_pattern = r'[_\-](\d+)$'
    match = re.search(suffix_pattern, name)

    if match:
        number = match.group(1)
        # Убираем суффикс из имени
        base_name = name[:match.start()]
        # Очищаем базовое имя от знаков препинания
        cleaned_base = ''.join(char for char in base_name if char not in string.punctuation)
        cleaned_base = ' '.join(cleaned_base.split())  # нормализация пробелов
        # Формируем новое имя с (N)
        new_name = f"{cleaned_base}({number}){ext}"
    else:
        # Нет суффикса — просто чистим всё
        cleaned_name = ''.join(char for char in name if char not in string.punctuation)
        cleaned_name = ' '.join(cleaned_name.split())
        new_name = cleaned_name + ext

    return new_name


def clean_filenames():
    """
    Функция 1: Очистка имён .jpg файлов от знаков препинания.
    Поддерживает преобразование _1, -2 → (1), (2).
    """
    folder_path = filedialog.askdirectory(title="Выберите папку с .jpg файлами (очистка имён)")
    if not folder_path:
        return

    if not os.path.exists(folder_path):
        messagebox.showerror("Ошибка", "Папка не существует.")
        return

    jpg_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.jpg')]
    if not jpg_files:
        messagebox.showinfo("Информация", "В папке нет .jpg файлов.")
        return

    renamed_count = 0
    errors = []

    for filename in jpg_files:
        old_path = os.path.join(folder_path, filename)
        new_filename = clean_filename(filename)
        new_path = os.path.join(folder_path, new_filename)

        if old_path == new_path:
            continue  # Имя уже чистое

        if os.path.exists(new_path):
            errors.append(f"Пропущено: {filename} → {new_filename} (файл уже существует)")
            continue

        try:
            os.rename(old_path, new_path)
            renamed_count += 1
        except Exception as e:
            errors.append(f"Ошибка при переименовании {filename}: {str(e)}")

    report = f"Успешно очищено: {renamed_count} файл(ов)."
    if errors:
        report += "\n\nОшибки:\n" + "\n".join(errors)
        messagebox.showwarning("Завершено с ошибками", report)
    else:
        messagebox.showinfo("Успех", report)


def filter_photos_by_excel():
    """
    Функция 2: Удаление .jpg файлов, если их имена (без .jpg) нет в списке артикулов из Excel.
    """
    # Выбор Excel-файла
    excel_path = filedialog.askopenfilename(
        title="Выберите Excel-файл с артикулами",
        filetypes=[("Excel files", "*.xlsx")]
    )
    if not excel_path:
        return

    # Выбор папки с фото
    folder_path = filedialog.askdirectory(title="Выберите папку с .jpg фото")
    if not folder_path:
        return

    if not os.path.exists(excel_path):
        messagebox.showerror("Ошибка", "Файл Excel не найден.")
        return
    if not os.path.exists(folder_path):
        messagebox.showerror("Ошибка", "Папка с фото не найдена.")
        return

    # Чтение артикулов из Excel
    try:
        workbook = openpyxl.load_workbook(excel_path)
        sheet = workbook.active
        sku_list = set()
        for row in sheet.iter_rows(values_only=True):
            cell_value = row[0]
            if cell_value:
                sku = str(cell_value).strip()
                if sku:
                    sku_list.add(sku)
        workbook.close()
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось прочитать Excel-файл:\n{str(e)}")
        return

    if not sku_list:
        messagebox.showwarning("Внимание", "Список артикулов пуст.")
        return

    # Получаем все .jpg файлы
    jpg_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.jpg')]
    deleted_count = 0
    errors = []

    for filename in jpg_files:
        base_name, ext = os.path.splitext(filename)
        if base_name not in sku_list:
            file_path = os.path.join(folder_path, filename)
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                errors.append(f"Не удалось удалить {filename}: {str(e)}")

    report = f"Удалено файлов: {deleted_count}"
    if errors:
        report += "\n\nОшибки при удалении:\n" + "\n".join(errors)
        messagebox.showwarning("Завершено с ошибками", report)
    else:
        messagebox.showinfo("Успех", report)


def organize_photos_in_folders():
    """
    Функция 3: Создаёт папку Febest, а в ней — подпапки по базовому имени файла.
    Файлы вида product(1).jpg, product(2).jpg идут в папку 'product',
    и внутри называются product.jpg, product_1.jpg, product_2.jpg и т.д.
    """
    folder_path = filedialog.askdirectory(title="Выберите папку с .jpg файлами (организация по папкам)")
    if not folder_path:
        return

    if not os.path.exists(folder_path):
        messagebox.showerror("Ошибка", "Папка не существует.")
        return

    jpg_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.jpg')]
    if not jpg_files:
        messagebox.showinfo("Информация", "В папке нет .jpg файлов.")
        return

    febest_path = os.path.join(folder_path, "Febest")
    os.makedirs(febest_path, exist_ok=True)

    copied_count = 0
    errors = []

    for filename in jpg_files:
        name, ext = os.path.splitext(filename)

        # Ищем суффикс вида (1), (2), (10) в конце имени
        match = re.search(r'\((\d+)\)$', name)
        if match:
            number = match.group(1)
            base_name = name[:match.start()].rstrip()  # убираем возможные пробелы
            # Имя внутри папки: base_name + '_' + number + ext
            target_filename = f"{base_name}_{number}{ext}"
        else:
            base_name = name
            target_filename = filename  # без изменений

        # Путь к подпапке = базовое имя
        subfolder_path = os.path.join(febest_path, base_name)
        try:
            os.makedirs(subfolder_path, exist_ok=True)
            src = os.path.join(folder_path, filename)
            dst = os.path.join(subfolder_path, target_filename)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                copied_count += 1
        except Exception as e:
            errors.append(f"Ошибка при копировании {filename}: {str(e)}")

    report = f"Успешно организовано: {copied_count} файл(ов) в папку Febest."
    if errors:
        report += "\n\nОшибки:\n" + "\n".join(errors)
        messagebox.showwarning("Завершено с ошибками", report)
    else:
        messagebox.showinfo("Успех", report)


# GUI
root = tk.Tk()
root.title("Многофункциональная обработка .jpg файлов")
root.geometry("600x400")
root.resizable(False, False)

frame = tk.Frame(root)
frame.pack(expand=True, padx=20, pady=20)

tk.Label(
    frame,
    text="Выберите действие:",
    font=("Arial", 14, "bold")
).pack(pady=15)

btn1 = tk.Button(
    frame,
    text="1. Очистить имена .jpg файлов от знаков препинания",
    command=clean_filenames,
    width=55,
    height=2
)
btn1.pack(pady=8)

btn2 = tk.Button(
    frame,
    text="2. Удалить .jpg файлы, которых нет в Excel (по артикулам)",
    command=filter_photos_by_excel,
    width=55,
    height=2
)
btn2.pack(pady=8)

btn3 = tk.Button(
    frame,
    text="3. Организовать .jpg файлы: каждая в свою папку в 'Febest'",
    command=organize_photos_in_folders,
    width=55,
    height=2
)
btn3.pack(pady=8)

footer = tk.Label(frame, text="© 2024", fg="gray")
footer.pack(side="bottom", pady=20)

root.mainloop()