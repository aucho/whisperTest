"""
HTTP API 使用示例

这个文件展示了如何通过 HTTP 请求调用音频转文字服务
"""

import requests
import json

# API 基础 URL
API_BASE_URL = "http://127.0.0.1:18000"

def example_1_basic_transcribe():
    """示例 1: 基本转写（使用默认参数）"""
    print("=" * 60)
    print("示例 1: 基本转写")
    print("=" * 60)
    
    # 准备文件
    audio_file_path = "your_audio.mp3"  # 替换为你的音频文件路径
    
    with open(audio_file_path, "rb") as f:
        files = {"file": ("audio.mp3", f, "audio/mpeg")}
        data = {}
        
        response = requests.post(f"{API_BASE_URL}/transcribe", files=files, data=data)
    
    if response.status_code == 200:
        result = response.json()
        print("转写成功！")
        print(f"文字内容: {result['text']}")
        if 'text_with_timestamps' in result:
            print(f"\n带时间戳的内容:\n{result['text_with_timestamps']}")
    else:
        print(f"错误: {response.status_code}")
        print(response.text)

def example_2_with_parameters():
    """示例 2: 使用自定义参数"""
    print("\n" + "=" * 60)
    print("示例 2: 使用自定义参数")
    print("=" * 60)
    
    audio_file_path = "your_audio.mp3"  # 替换为你的音频文件路径
    
    with open(audio_file_path, "rb") as f:
        files = {"file": ("audio.mp3", f, "audio/mpeg")}
        data = {
            "model_name": "small",  # 使用 small 模型
            "language": "en",       # 指定英语
            "include_timestamps": True
        }
        
        response = requests.post(f"{API_BASE_URL}/transcribe", files=files, data=data)
    
    if response.status_code == 200:
        result = response.json()
        print("转写成功！")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"错误: {response.status_code}")
        print(response.text)

def example_3_health_check():
    """示例 3: 健康检查"""
    print("\n" + "=" * 60)
    print("示例 3: 健康检查")
    print("=" * 60)
    
    response = requests.get(f"{API_BASE_URL}/health")
    
    if response.status_code == 200:
        result = response.json()
        print(f"服务状态: {result['status']}")
        print(f"设备: {result['device']}")
    else:
        print(f"错误: {response.status_code}")

def example_4_curl_command():
    """示例 4: cURL 命令示例"""
    print("\n" + "=" * 60)
    print("示例 4: cURL 命令")
    print("=" * 60)
    
    curl_command = """
# 基本转写
curl -X POST "http://127.0.0.1:18000/transcribe" \\
  -F "file=@your_audio.mp3" \\
  -F "model_name=base" \\
  -F "language=en" \\
  -F "include_timestamps=true"

# 健康检查
curl -X GET "http://127.0.0.1:18000/health"

# 查看 API 文档
# 浏览器访问: http://127.0.0.1:18000/docs
"""
    print(curl_command)

def example_5_python_requests():
    """示例 5: 使用 Python requests 库的完整示例"""
    print("\n" + "=" * 60)
    print("示例 5: Python requests 完整示例")
    print("=" * 60)
    
    import os
    
    audio_file_path = "your_audio.mp3"  # 替换为你的音频文件路径
    
    if not os.path.exists(audio_file_path):
        print(f"错误: 文件不存在 {audio_file_path}")
        print("请将 'your_audio.mp3' 替换为实际的音频文件路径")
        return
    
    try:
        with open(audio_file_path, "rb") as audio_file:
            files = {
                "file": (os.path.basename(audio_file_path), audio_file, "audio/mpeg")
            }
            data = {
                "model_name": "base",
                "language": None,  # None 表示自动检测
                "include_timestamps": True
            }
            
            print(f"正在上传文件: {audio_file_path}")
            print("处理中，请稍候...")
            
            response = requests.post(
                f"{API_BASE_URL}/transcribe",
                files=files,
                data=data,
                timeout=300  # 5分钟超时
            )
        
        if response.status_code == 200:
            result = response.json()
            print("\n✅ 转写成功！")
            print(f"\n📝 文字内容:\n{result['text']}")
            
            if 'text_with_timestamps' in result:
                print(f"\n⏱️  带时间戳的内容:\n{result['text_with_timestamps']}")
        else:
            print(f"\n❌ 错误: HTTP {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务器。请确保服务正在运行:")
        print("   python src/app.py")
    except FileNotFoundError:
        print(f"❌ 文件未找到: {audio_file_path}")
    except Exception as e:
        print(f"❌ 发生错误: {str(e)}")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("HTTP API 使用示例")
    print("=" * 60)
    print("\n请确保服务已启动: python src/app.py")
    print("\n可用的示例:")
    print("1. example_1_basic_transcribe() - 基本转写")
    print("2. example_2_with_parameters() - 使用自定义参数")
    print("3. example_3_health_check() - 健康检查")
    print("4. example_4_curl_command() - cURL 命令示例")
    print("5. example_5_python_requests() - Python requests 完整示例")
    print("\n" + "=" * 60)
    
    # 运行示例（取消注释以运行）
    # example_3_health_check()
    # example_4_curl_command()
    # example_5_python_requests()

