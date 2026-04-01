## Сценарий демонстрации

### 1. Запуск сервера

**Показывает**: однопоточный TCP‑сервер, работа по протоколу TCP, включённый SO_KEEPALIVE.

```bash
# В корне проекта
venv\Scripts\activate   # или source venv/bin/activate
python -m src.app --proto tcp --mode single --log-level DEBUG
```

Ожидаемый лог: `TCP single server started ...`

### 2. Сканирование порта (nmap)

**Показывает**: сервер слушает TCP‑порт, виден из сети.

```bash
nmap 127.0.0.1 -p 5000
```

В выводе порт 5000 должен быть `open`.

### 3. Просмотр открытых сокетов (netstat)

**Показывает**: наличие слушающего сокета и активных TCP‑подключений.

```Powershell
# Windows
netstat -ano | Select-String 5000
```

```bash
# Linux/macOS
netstat -tulpn | grep 5000
```

Должен быть процесс, слушающий `0.0.0.0:5000`. 

### 4. Команда HELLO + TIME через telnet/netcat

**Показывает**: текстовый TCP‑протокол, команда `TIME`, формат ответов.

```bash
# в другом терминале
telnet 127.0.0.1 5000
# или
nc 127.0.0.1 5000
```

Диалог:

```text
HELLO                # приходит от сервера автоматически
TIME
2026-03-31 10:15:23  # текущее время сервера
```

Сервер должен логировать подключение и получение команды `TIME`.

### 5. Команда ECHO через netcat

**Показывает**: команда `ECHO`, возврат данных клиента.

```text
ECHO hello world
hello world
```

Строка после ECHO возвращается клиенту.

### 6. Команда CLOSE (закрытие соединения)

**Показывает**: команда `CLOSE/EXIT/QUIT`, корректное завершение сеанса.

```text
CLOSE
BYE
```

После `BYE` telnet/netcat должен увидеть закрытие соединения, а сервер — лог `Client disconnected`.

### 7. DOWNLOAD существующего файла

**Показывает**: передача файла по TCP, DOWNLOAD, вывод битрейта.

```bash
cd client
python client_download.py bigtext.txt
```

Ожидаем:

- Строка прогресса вида:  
  ` 70% | Downloaded 356352 / 507904 bytes`
- Финальный ответ сервера с битрейтом:  
  `OK DOWNLOADED 507904 bytes in 0.005 s, 91560.22 KB/s`.

### 8. DOWNLOAD несуществующего файла

**Показывает**: корректное сообщение “файл не найден”.

```bash
python client_download.py no-such-file.txt
```

Ожидаем ответ сервера:

```text
ERROR file not found
```

Клиент выводит сообщение и завершает работу.

### 9. UPLOAD нового файла

**Показывает**: передача файла на сервер по TCP, команда UPLOAD, вывод битрейта.

```bash
cd client
python client_upload.py bigtext.txt
```

На клиенте:

- Прогресс: ` 40% | Uploaded 41943040 / 104857600 bytes`  
- В конце строка от сервера:  
  `OK UPLOADED 104857600 bytes in ... s, ... KB/s`. 

На сервере в каталоге `serverfiles` появляется загруженный файл.

### 10. Докачка / доскачка после обрыва

**Показывает**: восстановление передачи, работа с offset.

1. Запускаем download/upload файла.
2. В процессе передачи принудительно рвём соединение (Ctrl+C на клиенте или временно отключаем сеть).
3. Повторно запускаем:

   ```bash
   python client_download.py bigtext.txt
   # или
   python client_upload.py bigtext.txt
   ```