# Windows 部署指南

本指南介绍如何在 Windows 系统上使用 NSSM（Non-Sucking Service Manager）将 Whisper API 服务部署为 Windows 服务，实现开机自启和负载均衡。

## 前置要求

1. **Python 环境**
   - Python 3.8 或更高版本
   - 已安装项目依赖（见 `requirements.txt`）
   - Conda 或 venv 虚拟环境

2. **NSSM**
   - 下载地址：https://nssm.cc/download
   - 推荐下载最新版本的 Win64 版本

## 安装步骤

### 1. 安装 NSSM

1. 从 https://nssm.cc/download 下载 NSSM
2. 解压到任意目录，例如 `C:\tools\nssm`
3. 将 NSSM 添加到系统 PATH：
   - 右键"此电脑" → "属性" → "高级系统设置" → "环境变量"
   - 在"系统变量"中找到 `Path`，点击"编辑"
   - 点击"新建"，添加 NSSM 所在目录（如 `C:\tools\nssm\win64`）
   - 点击"确定"保存

4. 验证安装：
   ```cmd
   nssm version
   ```

### 2. 配置脚本路径

在安装服务之前，需要修改以下脚本中的路径配置：

#### 2.1 修改批处理启动脚本

编辑以下文件，根据实际情况修改 Python 环境路径：

- `scripts/start_api_18000.bat`
- `scripts/start_api_18001.bat`
- `scripts/start_api_18002.bat`

**如果使用 Conda：**
```batch
call C:\ProgramData\anaconda3\Scripts\activate.bat whisper2
```

**如果使用 venv：**
```batch
call venv\Scripts\activate.bat
```

#### 2.2 修改 NSSM 安装脚本

编辑 `scripts/install_nssm_services.bat`，修改以下变量：

```batch
REM Python 路径（请根据实际情况修改）
REM 如果使用 conda：
set PYTHON_EXE=C:\ProgramData\anaconda3\envs\whisper2\python.exe
REM 如果使用 venv：
REM set PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe
```

### 3. 安装服务

1. **以管理员身份运行命令提示符**
   - 按 `Win + X`，选择"Windows PowerShell (管理员)" 或 "命令提示符 (管理员)"

2. **切换到项目目录**
   ```cmd
   cd G:\repositories\AI\whisperTest
   ```

3. **运行安装脚本**
   ```cmd
   scripts\install_nssm_services.bat
   ```

4. **验证服务安装**
   ```cmd
   sc query WhisperAPI-18000
   sc query WhisperAPI-18001
   sc query WhisperAPI-18002
   ```

### 4. 启动服务

服务安装后会自动设置为"自动启动"，但不会立即启动。需要手动启动：

```cmd
net start WhisperAPI-18000
net start WhisperAPI-18001
net start WhisperAPI-18002
```

或者通过服务管理器启动：
1. 按 `Win + R`，输入 `services.msc`，回车
2. 找到 `Whisper API Service (Port 18000)`、`18001`、`18002`
3. 右键 → "启动"

## 服务管理

### 查看服务状态

```cmd
sc query WhisperAPI-18000
sc query WhisperAPI-18001
sc query WhisperAPI-18002
```

### 启动服务

```cmd
net start WhisperAPI-18000
net start WhisperAPI-18001
net start WhisperAPI-18002
```

### 停止服务

```cmd
net stop WhisperAPI-18000
net stop WhisperAPI-18001
net stop WhisperAPI-18002
```

### 重启服务

```cmd
net stop WhisperAPI-18000 && net start WhisperAPI-18000
```

### 查看服务日志

服务日志保存在项目根目录的 `logs` 文件夹中：
- `logs\service_18000.log`
- `logs\service_18001.log`
- `logs\service_18002.log`

## 访问服务

服务启动后，可以通过以下地址访问：

- **端口 18000**: http://127.0.0.1:18000
- **端口 18001**: http://127.0.0.1:18001
- **端口 18002**: http://127.0.0.1:18002

### API 文档

- Swagger UI: http://127.0.0.1:18000/docs
- ReDoc: http://127.0.0.1:18000/redoc

## 负载均衡配置（可选）

如果需要使用负载均衡，可以配置 Nginx 或其他反向代理服务器，将请求分发到三个端口。

参考 `config/nginx.conf` 中的配置示例。

## 卸载服务

如果需要卸载服务：

1. **以管理员身份运行命令提示符**

2. **运行卸载脚本**
   ```cmd
   cd G:\repositories\AI\whisperTest
   scripts\uninstall_nssm_services.bat
   ```

   或者手动卸载：
   ```cmd
   nssm remove WhisperAPI-18000 confirm
   nssm remove WhisperAPI-18001 confirm
   nssm remove WhisperAPI-18002 confirm
   ```

## 故障排除

### 服务无法启动

1. **检查日志**
   - 查看 `logs\service_18000.log` 等日志文件
   - 查看 Windows 事件查看器（`eventvwr.msc`）

2. **检查 Python 路径**
   - 确认 `install_nssm_services.bat` 中的 `PYTHON_EXE` 路径正确
   - 确认 Python 环境已安装所有依赖

3. **检查端口占用**
   ```cmd
   netstat -ano | findstr :18000
   netstat -ano | findstr :18001
   netstat -ano | findstr :18002
   ```

4. **手动测试启动脚本**
   ```cmd
   scripts\start_api_18000.bat
   ```
   如果手动运行失败，检查批处理脚本中的路径配置

### 服务启动后立即停止

1. **检查服务配置**
   ```cmd
   nssm edit WhisperAPI-18000
   ```
   检查"应用程序"、"工作目录"等设置

2. **检查环境变量**
   - 确认 Conda/venv 环境路径正确
   - 确认项目依赖已安装

### 服务无法自动启动

1. **检查服务启动类型**
   ```cmd
   sc config WhisperAPI-18000 start= auto
   ```

2. **检查服务依赖**
   - 确保服务依赖的服务已启动（如网络服务）

### 权限问题

- 确保以**管理员身份**运行安装和卸载脚本
- 确保服务账户有足够的权限访问项目目录和 Python 环境

## 高级配置

### 修改服务启动类型

```cmd
REM 自动启动
sc config WhisperAPI-18000 start= auto

REM 手动启动
sc config WhisperAPI-18000 start= demand

REM 禁用
sc config WhisperAPI-18000 start= disabled
```

### 使用 NSSM GUI 配置服务

```cmd
nssm edit WhisperAPI-18000
```

可以图形化界面修改服务配置，包括：
- 应用程序路径
- 工作目录
- 环境变量
- 日志设置
- 重启策略

### 设置服务账户

默认情况下，服务以 `LocalSystem` 账户运行。如果需要使用其他账户：

```cmd
nssm set WhisperAPI-18000 ObjectName ".\用户名" "密码"
```

## 注意事项

1. **路径配置**
   - 所有路径建议使用绝对路径，避免相对路径问题
   - 路径中包含空格时，使用引号包裹

2. **日志管理**
   - 日志文件会自动轮转（每天或达到 10MB）
   - 定期清理旧日志文件，避免占用过多磁盘空间

3. **资源占用**
   - 三个服务实例会占用更多内存和 CPU
   - 根据服务器性能调整实例数量

4. **防火墙**
   - 确保 Windows 防火墙允许相应端口的入站连接
   - 或配置防火墙规则允许 Python 程序访问网络

## 相关文件

- `scripts/run_api.py` - API 启动脚本（支持端口参数）
- `scripts/start_api_18000.bat` - 端口 18000 启动脚本
- `scripts/start_api_18001.bat` - 端口 18001 启动脚本
- `scripts/start_api_18002.bat` - 端口 18002 启动脚本
- `scripts/install_nssm_services.bat` - NSSM 服务安装脚本
- `scripts/uninstall_nssm_services.bat` - NSSM 服务卸载脚本

