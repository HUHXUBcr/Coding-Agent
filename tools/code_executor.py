import subprocess
import sys
import os
import tempfile
import json
import threading
import time
import uuid
import re
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
import logging

# MCP工具描述定义
CODE_EXECUTION_TOOLS = {
    "execute_code": {
        "name": "execute_code",
        "description": "Execute code in a specified programming language. Best for short code snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to execute"
                },
                "language": {
                    "type": "string",
                    "description": "Programming language",
                    "enum": ["python", "javascript", "java", "cpp", "c"],
                    "default": "python"
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename for the code file"
                }
            },
            "required": ["code"]
        }
    },
    "install_dependencies": {
        "name": "install_dependencies",
        "description": "Install Python packages in the environment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of package names to install"
                }
            },
            "required": ["packages"]
        }
    },
    "run_command": {
        "name": "run_command",
        "description": "Execute a system command with optional stdin input.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute"
                },
                "stdin": {
                    "type": "string",
                    "description": "Optional stdin input"
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for command execution"
                }
            },
            "required": ["command"]
        }
    }
}

class CodeExecutionTool:
    """
    代码执行工具，支持多种编程语言和执行模式
    基于MCP Code Executor的最佳实践设计
    """
    
    @classmethod
    def get_tool_descriptions(cls) -> Dict[str, Dict]:
        """获取所有工具的MCP描述"""
        return CODE_EXECUTION_TOOLS
    """
    代码执行工具，支持多种编程语言和执行模式
    """
    
    def __init__(self, timeout=10, max_output_size=1024*1024):  # 1MB max output
        """
        初始化代码执行工具
        
        Args:
            timeout: 执行超时时间（秒）
            max_output_size: 最大输出大小（字节）
        """
        self.timeout = timeout
        self.max_output_size = max_output_size
        self.temp_dir = tempfile.mkdtemp()
        
        # 支持的语言及其执行命令
        self.language_configs = {
            '.py': {
                'command': [sys.executable],
                'name': 'Python',
                'compile': False
            },
            '.js': {
                'command': ['node'],
                'name': 'JavaScript',
                'compile': False
            },
            '.java': {
                'command': ['java'],
                'name': 'Java',
                'compile': True,
                'compile_command': ['javac']
            },
            '.cpp': {
                'command': ['./a.out'] if os.name != 'nt' else ['a.exe'],
                'name': 'C++',
                'compile': True,
                'compile_command': ['g++', '-o', 'a.out'] if os.name != 'nt' else ['g++', '-o', 'a.exe']
            },
            '.c': {
                'command': ['./a.out'] if os.name != 'nt' else ['a.exe'],
                'name': 'C',
                'compile': True,
                'compile_command': ['gcc', '-o', 'a.out'] if os.name != 'nt' else ['gcc', '-o', 'a.exe']
            }
        }
        
        # 执行历史
        self.execution_history = []
        
        # 代码文件管理
        self.code_files = {}  # 管理创建的代码文件
        
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        MCP标准工具执行接口
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            MCP标准响应格式
        """
        try:
            if tool_name == "execute_code":
                return self._execute_code_tool(arguments)
            elif tool_name == "install_dependencies":
                return self._install_dependencies_tool(arguments)
            elif tool_name == "run_command":
                return self._run_command_tool(arguments)
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                    "isError": True
                }
        except Exception as e:
            logging.error(f"Tool execution error: {str(e)}")
            return {
                "content": [{"type": "text", "text": f"Tool execution failed: {str(e)}"}],
                "isError": True
            }
    
    def _execute_code_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行代码工具实现"""
        code = arguments.get("code")
        language = arguments.get("language", "python")
        filename = arguments.get("filename")
        
        if not code:
            return {
                "content": [{"type": "text", "text": "Error: Code parameter is required"}],
                "isError": True
            }
        
        result = self.run_code_string(code, language, filename)
        
        # 格式化输出
        output_text = f"**Code Execution Result ({result['language']})**\n\n"
        
        if result['returncode'] == 0:
            output_text += f"**Status:** Success\n"
            if result['stdout']:
                output_text += f"**Output:**\n```\n{result['stdout']}\n```\n"
        else:
            output_text += f"**Status:** Failed (exit code: {result['returncode']})\n"
            if result['stderr']:
                output_text += f"**Error:**\n```\n{result['stderr']}\n```\n"
        
        output_text += f"**Execution Time:** {result['execution_time']:.3f} seconds"
        
        return {
            "content": [{"type": "text", "text": output_text}],
            "isError": result['returncode'] != 0
        }
    
    def _install_dependencies_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """安装依赖包工具实现"""
        packages = arguments.get("packages", [])
        
        if not packages:
            return {
                "content": [{"type": "text", "text": "Error: Packages list is required"}],
                "isError": True
            }
        
        results = []
        for package in packages:
            try:
                cmd = [sys.executable, "-m", "pip", "install", package]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    results.append(f"✅ {package}: Installed successfully")
                else:
                    results.append(f"❌ {package}: Installation failed - {result.stderr}")
            except Exception as e:
                results.append(f"❌ {package}: Error - {str(e)}")
        
        output_text = "**Package Installation Results:**\n\n" + "\n".join(results)
        
        return {
            "content": [{"type": "text", "text": output_text}],
            "isError": False
        }
    
    def _run_command_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行系统命令工具实现"""
        command = arguments.get("command")
        stdin_input = arguments.get("stdin")
        working_dir = arguments.get("working_directory", os.getcwd())
        
        if not command:
            return {
                "content": [{"type": "text", "text": "Error: Command parameter is required"}],
                "isError": True
            }
        
        try:
            # 分解命令
            if isinstance(command, str):
                import shlex
                cmd_parts = shlex.split(command)
            else:
                cmd_parts = command
            
            # 执行命令
            proc = subprocess.run(
                cmd_parts,
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=working_dir
            )
            
            # 格式化输出
            output_text = f"**Command Execution Result**\n\n"
            output_text += f"**Command:** `{' '.join(cmd_parts)}`\n"
            output_text += f"**Working Directory:** `{working_dir}`\n"
            output_text += f"**Exit Code:** {proc.returncode}\n\n"
            
            if proc.stdout:
                output_text += f"**STDOUT:**\n```\n{proc.stdout}\n```\n\n"
            
            if proc.stderr:
                output_text += f"**STDERR:**\n```\n{proc.stderr}\n```\n"
            
            return {
                "content": [{"type": "text", "text": output_text}],
                "isError": proc.returncode != 0
            }
            
        except subprocess.TimeoutExpired:
            return {
                "content": [{"type": "text", "text": f"Command timed out after {self.timeout} seconds"}],
                "isError": True
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Command execution failed: {str(e)}"}],
                "isError": True
            }
    
    def run_python_file(self, path: str) -> Dict[str, Any]:
        """
        执行Python文件（保持向后兼容）
        
        Args:
            path: Python文件路径
            
        Returns:
            执行结果字典
        """
        return self.run_file(path)
    
    def run_file(self, path: str, args: List[str] = None, env_vars: Dict[str, str] = None) -> Dict[str, Any]:
        """
        执行指定文件
        
        Args:
            path: 文件路径
            args: 命令行参数
            env_vars: 环境变量
            
        Returns:
            执行结果字典
        """
        start_time = time.time()
        
        try:
            # 检查文件是否存在
            if not os.path.exists(path):
                return {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"File not found: {path}",
                    "execution_time": 0,
                    "language": "unknown"
                }
            
            # 获取文件扩展名
            file_ext = Path(path).suffix.lower()
            
            if file_ext not in self.language_configs:
                return {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"Unsupported file type: {file_ext}",
                    "execution_time": 0,
                    "language": "unknown"
                }
            
            config = self.language_configs[file_ext]
            language = config['name']
            
            # 编译步骤（如果需要）
            if config.get('compile', False):
                compile_result = self._compile_file(path, config)
                if compile_result['returncode'] != 0:
                    execution_time = time.time() - start_time
                    return {
                        "returncode": compile_result['returncode'],
                        "stdout": compile_result['stdout'],
                        "stderr": f"Compilation failed: {compile_result['stderr']}",
                        "execution_time": execution_time,
                        "language": language
                    }
            
            # 构建执行命令
            command = config['command'].copy()
            
            # 对于解释型语言，添加文件路径
            if not config.get('compile', False):
                command.append(path)
            
            # 添加命令行参数
            if args:
                command.extend(args)
            
            # 设置环境变量
            env = os.environ.copy()
            if env_vars:
                env.update(env_vars)
            
            # 执行命令
            result = self._execute_command(command, env, os.path.dirname(path))
            execution_time = time.time() - start_time
            
            # 记录执行历史
            history_entry = {
                "timestamp": time.time(),
                "file_path": path,
                "language": language,
                "command": ' '.join(command),
                "returncode": result['returncode'],
                "execution_time": execution_time,
                "success": result['returncode'] == 0
            }
            self.execution_history.append(history_entry)
            
            return {
                "returncode": result['returncode'],
                "stdout": result['stdout'],
                "stderr": result['stderr'],
                "execution_time": execution_time,
                "language": language
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": execution_time,
                "language": "unknown"
            }
    
    def _compile_file(self, path: str, config: Dict) -> Dict[str, Any]:
        """
        编译源代码文件
        
        Args:
            path: 源文件路径
            config: 语言配置
            
        Returns:
            编译结果
        """
        compile_command = config['compile_command'].copy()
        compile_command.append(path)
        
        return self._execute_command(compile_command, os.environ.copy(), os.path.dirname(path))
    
    def _execute_command(self, command: List[str], env: Dict[str, str], cwd: str) -> Dict[str, Any]:
        """
        执行系统命令
        
        Args:
            command: 命令列表
            env: 环境变量
            cwd: 工作目录
            
        Returns:
            执行结果
        """
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=cwd
            )
            
            # 限制输出大小
            stdout = proc.stdout
            stderr = proc.stderr
            
            if len(stdout) > self.max_output_size:
                stdout = stdout[:self.max_output_size] + "\n... (output truncated)"
            
            if len(stderr) > self.max_output_size:
                stderr = stderr[:self.max_output_size] + "\n... (output truncated)"
            
            return {
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr
            }
            
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {self.timeout} seconds"
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }
    
    def run_code_string(self, code: str, language: str = "python", filename: str = None) -> Dict[str, Any]:
        """
        执行代码字符串
        
        Args:
            code: 代码内容
            language: 编程语言
            filename: 临时文件名（可选）
            
        Returns:
            执行结果
        """
        # 语言到文件扩展名的映射
        lang_to_ext = {
            "python": ".py",
            "javascript": ".js",
            "java": ".java",
            "cpp": ".cpp",
            "c": ".c"
        }
        
        file_ext = lang_to_ext.get(language.lower(), ".py")
        
        # 创建临时文件
        if filename is None:
            filename = f"temp_code_{int(time.time())}{file_ext}"
        
        temp_file_path = os.path.join(self.temp_dir, filename)
        
        try:
            # 写入代码到临时文件
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 执行文件
            result = self.run_file(temp_file_path)
            
            return result
            
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": 0,
                "language": language
            }
        finally:
            # 清理临时文件
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass  # 忽略删除失败
    
    def validate_syntax(self, code: str, language: str = "python") -> Dict[str, Any]:
        """
        验证代码语法
        
        Args:
            code: 代码内容
            language: 编程语言
            
        Returns:
            验证结果
        """
        if language.lower() == "python":
            try:
                compile(code, '<string>', 'exec')
                return {
                    "valid": True,
                    "error": None,
                    "language": language
                }
            except SyntaxError as e:
                return {
                    "valid": False,
                    "error": f"语法错误在第{e.lineno}行: {e.msg}",
                    "language": language,
                    "line_number": e.lineno
                }
            except Exception as e:
                return {
                    "valid": False,
                    "error": str(e),
                    "language": language
                }
        else:
            # 对于其他语言，尝试编译来验证语法
            result = self.run_code_string(code, language)
            return {
                "valid": result['returncode'] == 0,
                "error": result['stderr'] if result['returncode'] != 0 else None,
                "language": language
            }
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """
        获取执行统计信息
        
        Returns:
            统计信息字典
        """
        if not self.execution_history:
            return {
                "total_executions": 0,
                "success_rate": 0,
                "avg_execution_time": 0,
                "languages_used": [],
                "most_used_language": None
            }
        
        total = len(self.execution_history)
        successful = len([h for h in self.execution_history if h['success']])
        avg_time = sum(h['execution_time'] for h in self.execution_history) / total
        
        languages = [h['language'] for h in self.execution_history]
        language_counts = {}
        for lang in languages:
            language_counts[lang] = language_counts.get(lang, 0) + 1
        
        most_used = max(language_counts, key=language_counts.get) if language_counts else None
        
        return {
            "total_executions": total,
            "success_rate": (successful / total) * 100,
            "avg_execution_time": avg_time,
            "languages_used": list(set(languages)),
            "most_used_language": most_used,
            "language_distribution": language_counts
        }
    
    def clear_history(self):
        """清除执行历史"""
        self.execution_history.clear()
    
    def set_timeout(self, timeout: int):
        """设置执行超时时间"""
        self.timeout = timeout
    
    def check_dependencies(self, language: str) -> Dict[str, Any]:
        """
        检查运行环境依赖
        
        Args:
            language: 编程语言
            
        Returns:
            依赖检查结果
        """
        results = {}
        
        if language.lower() == "python":
            try:
                result = subprocess.run([sys.executable, '--version'], 
                                      capture_output=True, text=True, timeout=5)
                results['python'] = {
                    'available': result.returncode == 0,
                    'version': result.stdout.strip() if result.returncode == 0 else 'Not found'
                }
            except:
                results['python'] = {'available': False, 'version': 'Not found'}
        
        elif language.lower() == "javascript":
            try:
                result = subprocess.run(['node', '--version'], 
                                      capture_output=True, text=True, timeout=5)
                results['node'] = {
                    'available': result.returncode == 0,
                    'version': result.stdout.strip() if result.returncode == 0 else 'Not found'
                }
            except:
                results['node'] = {'available': False, 'version': 'Not found'}
        
        elif language.lower() == "java":
            try:
                result = subprocess.run(['java', '-version'], 
                                      capture_output=True, text=True, timeout=5)
                results['java'] = {
                    'available': result.returncode == 0,
                    'version': result.stderr.split('\n')[0] if result.returncode == 0 else 'Not found'
                }
            except:
                results['java'] = {'available': False, 'version': 'Not found'}
        
        return results
    
    def initialize_code_file(self, content: str, filename: str = None) -> str:
        """
        初始化代码文件（增量代码生成的第一步）
        
        Args:
            content: 初始代码内容
            filename: 文件名（可选）
            
        Returns:
            创建的文件路径
        """
        if filename is None:
            filename = f"code_{uuid.uuid4().hex[:8]}.py"
        elif not filename.endswith('.py'):
            filename += '.py'
            
        file_path = os.path.join(self.temp_dir, filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 记录文件
        self.code_files[filename] = file_path
        
        return file_path
    
    def append_to_code_file(self, file_path: str, content: str) -> bool:
        """
        向现有代码文件追加内容
        
        Args:
            file_path: 文件路径
            content: 要追加的内容
            
        Returns:
            是否成功
        """
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write("\n" + content)
            return True
        except Exception as e:
            logging.error(f"Failed to append to file {file_path}: {str(e)}")
            return False
    
    def read_code_file(self, file_path: str) -> str:
        """
        读取代码文件内容
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件内容
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logging.error(f"Failed to read file {file_path}: {str(e)}")
            return ""
    
    def execute_code_file(self, file_path: str) -> Dict[str, Any]:
        """
        执行代码文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            执行结果
        """
        return self.run_file(file_path)
    
    def get_code_files(self) -> Dict[str, str]:
        """获取所有管理的代码文件"""
        return self.code_files.copy()
    
    def check_installed_packages(self, packages: List[str]) -> Dict[str, bool]:
        """
        检查Python包是否已安装
        
        Args:
            packages: 包名列表
            
        Returns:
            包安装状态字典
        """
        results = {}
        for package in packages:
            try:
                __import__(package)
                results[package] = True
            except ImportError:
                try:
                    import importlib.util
                    spec = importlib.util.find_spec(package)
                    results[package] = spec is not None
                except:
                    results[package] = False
        
        return results
    
    def get_environment_info(self) -> Dict[str, Any]:
        """获取现在的执行环境信息"""
        return {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "working_directory": os.getcwd(),
            "temp_directory": self.temp_dir,
            "timeout": self.timeout,
            "max_output_size": self.max_output_size,
            "supported_languages": list(self.language_configs.keys()),
            "managed_files": len(self.code_files)
        }
    
    def get_detailed_stats(self) -> Dict[str, Any]:
        """获取详细的统计信息"""
        basic_stats = self.get_execution_stats()
        
        # 添加更多统计信息
        recent_executions = [h for h in self.execution_history if time.time() - h['timestamp'] < 3600]  # 近一小时
        
        basic_stats.update({
            "recent_executions_count": len(recent_executions),
            "environment_info": self.get_environment_info(),
            "error_patterns": self._analyze_error_patterns()
        })
        
        return basic_stats
    
    def _analyze_error_patterns(self) -> Dict[str, int]:
        """分析常见错误模式"""
        error_patterns = {}
        
        for entry in self.execution_history:
            if not entry['success']:
                # 这里可以添加更复杂的错误分类逻辑
                language = entry.get('language', 'unknown')
                error_key = f"{language}_error"
                error_patterns[error_key] = error_patterns.get(error_key, 0) + 1
        
        return error_patterns
    
    # ==================== Web文件验证功能 ====================
    
    def validate_html_file(self, file_path: str, check_file_existence: bool = False, base_dir: str = None) -> Dict[str, Any]:
        """
        验证HTML文件的基本结构和语法
        
        Args:
            file_path: HTML文件路径
            check_file_existence: 是否检查外部引用文件的存在性
            base_dir: 用于检查文件存在性的基础目录，默认为HTML文件所在目录
            
        Returns:
            {
                "valid": bool,
                "errors": List[str],
                "warnings": List[str],
                "element_ids": Set[str],  # 提取的所有元素ID
                "external_refs": {  # 外部引用
                    "css": List[str],
                    "js": List[str],
                    "images": List[str]
                },
                "missing_files": {  # 缺失的文件引用
                    "css": List[str],
                    "js": List[str],
                    "images": List[str]
                }
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"valid": False, "errors": [f"Failed to read file: {str(e)}"], "warnings": []}
        
        errors = []
        warnings = []
        element_ids = set()
        external_refs = {"css": [], "js": [], "images": []}
        missing_files = {"css": [], "js": [], "images": []}
        
        # 基本结构检查
        if not re.search(r'<!DOCTYPE\s+html>', content, re.IGNORECASE):
            warnings.append("Missing DOCTYPE declaration")
        
        if not re.search(r'<html[^>]*>', content, re.IGNORECASE):
            errors.append("Missing <html> tag")
        
        if not re.search(r'<head[^>]*>.*</head>', content, re.IGNORECASE | re.DOTALL):
            warnings.append("Missing or empty <head> section")
        
        if not re.search(r'<body[^>]*>.*</body>', content, re.IGNORECASE | re.DOTALL):
            errors.append("Missing <body> section")
        
        # 提取所有 id 属性
        id_pattern = r'id=["\']([^"\']+)["\']'
        element_ids = set(re.findall(id_pattern, content))
        
        # 提取外部资源引用
        # CSS links
        css_pattern = r'<link[^>]+href=["\']([^"\']+\.css)["\']'
        external_refs["css"] = re.findall(css_pattern, content, re.IGNORECASE)
        
        # JS scripts
        js_pattern = r'<script[^>]+src=["\']([^"\']+\.js)["\']'
        external_refs["js"] = re.findall(js_pattern, content, re.IGNORECASE)
        
        # Images
        img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
        external_refs["images"] = re.findall(img_pattern, content, re.IGNORECASE)
        
        # 检查文件存在性
        if check_file_existence:
            if base_dir is None:
                base_dir = os.path.dirname(file_path)
            
            # 检查CSS文件存在性
            for css_ref in external_refs["css"]:
                if not self._check_file_existence(css_ref, base_dir):
                    missing_files["css"].append(css_ref)
                    errors.append(f"引用的CSS文件不存在: {css_ref}")
            
            # 检查JS文件存在性
            for js_ref in external_refs["js"]:
                if not self._check_file_existence(js_ref, base_dir):
                    missing_files["js"].append(js_ref)
                    errors.append(f"引用的JS文件不存在: {js_ref}")
            
            # 检查图片文件存在性
            for img_ref in external_refs["images"]:
                if not img_ref.startswith(('http://', 'https://')) and not self._check_file_existence(img_ref, base_dir):
                    missing_files["images"].append(img_ref)
                    warnings.append(f"引用的图片文件可能不存在: {img_ref}")
        
        # 检查标签配对（简单检查）
        open_tags = re.findall(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>', content)
        close_tags = re.findall(r'</([a-zA-Z][a-zA-Z0-9]*)>', content)
        
        # 自闭合标签不需要配对
        self_closing = {'img', 'br', 'hr', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'param', 'source', 'track', 'wbr'}
        open_tags = [tag for tag in open_tags if tag.lower() not in self_closing]
        
        if len(open_tags) != len(close_tags):
            warnings.append(f"Possible tag mismatch: {len(open_tags)} opening tags, {len(close_tags)} closing tags")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "element_ids": element_ids,
            "external_refs": external_refs,
            "missing_files": missing_files
        }
    
    def _check_file_existence(self, referenced_path: str, base_dir: str) -> bool:
        """
        检查引用的文件是否存在
        
        Args:
            referenced_path: 引用的相对路径
            base_dir: 基础目录
            
        Returns:
            文件是否存在
        """
        # 处理相对路径中的父目录引用
        normalized_path = os.path.normpath(referenced_path)
        full_path = os.path.join(base_dir, normalized_path)
        return os.path.exists(full_path)
    
    def validate_file_references_in_real_time(self, file_path: str, project_files: List[str]) -> Dict[str, Any]:
        """
        实时验证文件引用关系，检查引用的文件是否存在
        
        Args:
            file_path: 要验证的文件路径
            project_files: 项目中所有文件的路径列表
            
        Returns:
            验证结果
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "missing_refs": [],
            "suggestions": []
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"无法读取文件: {str(e)}")
            return result
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # 构建项目文件映射
        file_mapping = {}
        for proj_file in project_files:
            filename = os.path.basename(proj_file)
            file_mapping[filename] = proj_file
            # 添加相对路径映射
            relative_to_current = os.path.relpath(proj_file, os.path.dirname(file_path))
            file_mapping[relative_to_current] = proj_file
            # 添加相对于项目根目录的路径
            project_root = self._find_project_root(project_files)
            if project_root:
                rel_to_root = os.path.relpath(proj_file, project_root)
                file_mapping[rel_to_root] = proj_file
        
        if file_ext == '.html':
            # 验证HTML文件引用
            css_refs = re.findall(r'href=["\']([^"\']+\.css)["\']', content, re.IGNORECASE)
            js_refs = re.findall(r'src=["\']([^"\']+\.js)["\']', content, re.IGNORECASE)
            
            # 检查JavaScript文件加载顺序
            js_loading_order = self._check_js_loading_order(js_refs, file_mapping)
            if js_loading_order["warnings"]:
                result["warnings"].extend(js_loading_order["warnings"])
            if js_loading_order["suggestions"]:
                result["suggestions"].extend(js_loading_order["suggestions"])
            
            for css_ref in css_refs:
                if not self._check_reference_exists(css_ref, file_path, file_mapping):
                    result["errors"].append(f"CSS文件引用不存在: {css_ref}")
                    result["missing_refs"].append({"type": "css", "ref": css_ref})
                    result["valid"] = False
                    # 提供建议
                    suggestion = self._suggest_file_path(css_ref, file_mapping, 'css')
                    if suggestion:
                        result["suggestions"].append(f"建议使用: {suggestion}")
            
            for js_ref in js_refs:
                if not self._check_reference_exists(js_ref, file_path, file_mapping):
                    result["errors"].append(f"JS文件引用不存在: {js_ref}")
                    result["missing_refs"].append({"type": "js", "ref": js_ref})
                    result["valid"] = False
                    # 提供建议
                    suggestion = self._suggest_file_path(js_ref, file_mapping, 'js')
                    if suggestion:
                        result["suggestions"].append(f"建议使用: {suggestion}")
        
        elif file_ext == '.js':
            # 验证JS文件引用
            data_refs = re.findall(r'(?:fetch|import)\(["\']([^"\']+\.json)["\']', content, re.IGNORECASE)
            
            for data_ref in data_refs:
                if not self._check_reference_exists(data_ref, file_path, file_mapping):
                    result["warnings"].append(f"数据文件引用可能不存在: {data_ref}")
                    result["missing_refs"].append({"type": "data", "ref": data_ref})
                    # 提供建议
                    suggestion = self._suggest_file_path(data_ref, file_mapping, 'json')
                    if suggestion:
                        result["suggestions"].append(f"建议使用: {suggestion}")
        
        return result
    
    def _check_reference_exists(self, ref_path: str, source_file: str, file_mapping: Dict[str, str]) -> bool:
        """
        检查引用路径是否存在
        
        Args:
            ref_path: 引用路径
            source_file: 源文件路径
            file_mapping: 文件映射字典
            
        Returns:
            引用是否存在
        """
        # 如果引用路径在映射中，直接检查
        if ref_path in file_mapping:
            return os.path.exists(file_mapping[ref_path])
        
        # 尝试解析相对路径
        source_dir = os.path.dirname(source_file)
        
        # 处理相对路径
        if ref_path.startswith('./'):
            ref_path = ref_path[2:]  # 移除 './'
        
        # 构建完整路径
        full_path = os.path.join(source_dir, ref_path)
        
        # 检查文件是否存在
        if os.path.exists(full_path):
            return True
        
        # 尝试在项目根目录查找
        project_root = self._find_project_root(list(file_mapping.values()))
        if project_root:
            full_path_from_root = os.path.join(project_root, ref_path)
            if os.path.exists(full_path_from_root):
                return True
        
        # 检查是否为文件名（不含路径）
        filename = os.path.basename(ref_path)
        for mapped_path in file_mapping.values():
            if os.path.basename(mapped_path) == filename:
                return True
        
        return False
    
    def _suggest_file_path(self, ref_path: str, file_mapping: Dict[str, str], file_type: str) -> Optional[str]:
        """
        为不存在的引用路径提供建议
        
        Args:
            ref_path: 引用路径
            file_mapping: 文件映射字典
            file_type: 文件类型
            
        Returns:
            建议的路径，如果没有建议则返回None
        """
        filename = os.path.basename(ref_path)
        
        # 查找项目中同类型的文件
        matching_files = []
        for mapped_path in file_mapping.values():
            if mapped_path.endswith(f'.{file_type}'):
                if filename in os.path.basename(mapped_path):
                    # 计算相对路径
                    relative_path = os.path.relpath(mapped_path, os.path.dirname(list(file_mapping.keys())[0]))
                    matching_files.append(relative_path)
        
        if matching_files:
            # 返回最接近的匹配
            return min(matching_files, key=len)
        
        return None
    
    def _check_js_loading_order(self, js_refs: List[str], file_mapping: Dict[str, str]) -> Dict[str, List[str]]:
        """
        检查JavaScript文件加载顺序是否正确
        
        Args:
            js_refs: JavaScript引用路径列表
            file_mapping: 文件映射字典
            
        Returns:
            包含警告和建议的字典
        """
        result = {"warnings": [], "suggestions": []}
        
        if len(js_refs) < 2:
            return result
        
        # 定义文件类型和推荐顺序
        file_types = {
            "core": ["paper-list.js", "app.js", "main.js"],
            "navigation": ["navigation.js", "router.js"],
            "utilities": ["citation-tools.js", "utils.js", "helpers.js"]
        }
        
        # 分析每个引用的文件类型
        ref_types = []
        for js_ref in js_refs:
            filename = os.path.basename(js_ref)
            ref_type = "unknown"
            
            for file_type, patterns in file_types.items():
                if any(pattern in filename for pattern in patterns):
                    ref_type = file_type
                    break
            
            ref_types.append((js_ref, ref_type))
        
        # 检查加载顺序
        expected_order = ["core", "navigation", "utilities", "unknown"]
        current_order = [ref_type for _, ref_type in ref_types]
        
        # 检查是否违反推荐顺序
        for i in range(len(current_order) - 1):
            current_type = current_order[i]
            next_type = current_order[i + 1]
            
            current_index = expected_order.index(current_type) if current_type in expected_order else len(expected_order)
            next_index = expected_order.index(next_type) if next_type in expected_order else len(expected_order)
            
            if current_index > next_index:
                result["warnings"].append(
                    f"JavaScript文件加载顺序可能不正确: {ref_types[i][0]} ({current_type}) 应该在 {ref_types[i+1][0]} ({next_type}) 之后加载"
                )
                result["suggestions"].append(
                    f"建议调整script标签顺序: 先加载核心逻辑文件，再加载导航文件，最后加载工具文件"
                )
                break
        
        return result
    
    def _find_project_root(self, file_paths: List[str]) -> Optional[str]:
        """
        查找项目根目录
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            项目根目录路径，如果无法确定则返回None
        """
        if not file_paths:
            return None
        
        # 获取所有文件的公共父目录
        common_dir = os.path.commonpath([os.path.dirname(p) for p in file_paths])
        
        # 检查常见项目根目录标识
        for root_dir in [common_dir] + [os.path.dirname(common_dir)]:
            if os.path.exists(root_dir):
                # 检查是否有常见的项目配置文件
                project_files = ['package.json', 'requirements.txt', 'pyproject.toml', 
                               'README.md', '.git', 'src', 'public']
                for proj_file in project_files:
                    if os.path.exists(os.path.join(root_dir, proj_file)):
                        return root_dir
        
        return common_dir
    
    def validate_javascript_file(self, file_path: str, related_html_ids: Set[str] = None) -> Dict[str, Any]:
        """
        验证JavaScript文件的语法和DOM访问
        
        Args:
            file_path: JS文件路径
            related_html_ids: 相关HTML文件中的元素ID集合
            
        Returns:
            {
                "valid": bool,
                "syntax_errors": List[str],
                "warnings": List[str],
                "used_ids": Set[str],  # JS中使用的元素ID
                "missing_ids": Set[str],  # JS中使用但HTML中不存在的ID
                "external_refs": List[str]  # 引用的外部文件
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"valid": False, "syntax_errors": [f"Failed to read file: {str(e)}"], "warnings": []}
        
        syntax_errors = []
        warnings = []
        used_ids = set()
        external_refs = []
        
        # 使用 Node.js 检查语法（如果可用）
        try:
            # 创建临时文件进行语法检查
            temp_file = os.path.join(self.temp_dir, f"syntax_check_{uuid.uuid4().hex[:8]}.js")
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            result = subprocess.run(
                ['node', '--check', temp_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                syntax_errors.append(f"Syntax error: {result.stderr}")
            
            # 清理临时文件
            try:
                os.remove(temp_file)
            except:
                pass
                
        except FileNotFoundError:
            warnings.append("Node.js not available, skipping syntax check")
        except Exception as e:
            warnings.append(f"Syntax check failed: {str(e)}")
        
        # 提取使用的元素ID
        # getElementById
        id_patterns = [
            r'getElementById\(["\']([^"\']+)["\']\)',
            r'querySelector\(["\']#([^"\']+)["\']\)',
            r'querySelectorAll\(["\']#([^"\']+)["\']?\)'
        ]
        
        for pattern in id_patterns:
            found_ids = re.findall(pattern, content)
            used_ids.update(found_ids)
        
        # 提取 fetch/import 引用
        fetch_pattern = r'(?:fetch|import)\(["\']([^"\']+)["\']'
        external_refs = re.findall(fetch_pattern, content)
        
        # 检查ID是否存在于HTML中
        missing_ids = set()
        if related_html_ids is not None:
            missing_ids = used_ids - related_html_ids
        
        if missing_ids:
            warnings.append(f"IDs used in JS but not found in HTML: {', '.join(missing_ids)}")
        
        return {
            "valid": len(syntax_errors) == 0,
            "syntax_errors": syntax_errors,
            "warnings": warnings,
            "used_ids": used_ids,
            "missing_ids": missing_ids,
            "external_refs": external_refs
        }
    
    def validate_css_file(self, file_path: str) -> Dict[str, Any]:
        """
        验证CSS文件的基本语法
        
        Returns:
            {
                "valid": bool,
                "errors": List[str],
                "warnings": List[str],
                "selectors": List[str]  # CSS选择器列表
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"valid": False, "errors": [f"Failed to read file: {str(e)}"], "warnings": []}
        
        errors = []
        warnings = []
        selectors = []
        
        # 基本语法检查：括号匹配
        open_braces = content.count('{')
        close_braces = content.count('}')
        
        if open_braces != close_braces:
            errors.append(f"Brace mismatch: {open_braces} opening, {close_braces} closing")
        
        # 提取选择器
        selector_pattern = r'([^{}]+)\s*\{'
        selectors = re.findall(selector_pattern, content)
        selectors = [s.strip() for s in selectors if s.strip()]
        
        # 检查常见错误
        if re.search(r'}\s*[^}{\s]', content):
            warnings.append("Possible missing semicolon or brace")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "selectors": selectors
        }
    
    def validate_json_file(self, file_path: str, expected_schema: Dict = None) -> Dict[str, Any]:
        """
        验证JSON文件的语法和结构
        
        Args:
            file_path: JSON文件路径
            expected_schema: 期望的数据结构（可选）
            
        Returns:
            {
                "valid": bool,
                "errors": List[str],
                "warnings": List[str],
                "data": Dict,  # 解析后的数据
                "root_keys": List[str]  # 顶层键
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"valid": False, "errors": [f"Failed to read file: {str(e)}"], "warnings": []}
        
        errors = []
        warnings = []
        data = None
        root_keys = []
        
        # 解析JSON
        try:
            data = json.loads(content)
            
            if isinstance(data, dict):
                root_keys = list(data.keys())
            elif isinstance(data, list):
                warnings.append("JSON root is an array, not an object")
            
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error at line {e.lineno}: {e.msg}")
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
                "data": None,
                "root_keys": []
            }
        
        # 检查期望的schema
        if expected_schema and isinstance(data, dict):
            for key, expected_type in expected_schema.items():
                if key not in data:
                    warnings.append(f"Missing expected key: {key}")
                elif expected_type and not isinstance(data[key], expected_type):
                    warnings.append(f"Key '{key}' has unexpected type: expected {expected_type.__name__}, got {type(data[key]).__name__}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "data": data,
            "root_keys": root_keys
        }
    
    def validate_cross_file_consistency(self, html_file: str, js_file: str, json_file: str = None) -> Dict[str, Any]:
        """
        验证HTML、JS和JSON文件之间的一致性

        Returns:
            {
                "consistent": bool,
                "issues": List[str],
                "html_ids": Set[str],
                "js_used_ids": Set[str],
                "missing_ids": Set[str],
                "json_structure": Dict
            }
        """
        issues = []

        # 验证HTML
        html_result = self.validate_html_file(html_file)
        if not html_result["valid"]:
            issues.extend([f"HTML: {err}" for err in html_result["errors"]])

        html_ids = html_result.get("element_ids", set())

        # 验证JS
        js_result = self.validate_javascript_file(js_file, html_ids)
        if not js_result["valid"]:
            issues.extend([f"JS: {err}" for err in js_result["syntax_errors"]])

        js_used_ids = js_result.get("used_ids", set())
        missing_ids = js_result.get("missing_ids", set())

        if missing_ids:
            issues.append(f"JS references non-existent HTML IDs: {', '.join(missing_ids)}")

        # 验证JSON（如果提供）
        json_structure = None
        if json_file and os.path.exists(json_file):
            json_result = self.validate_json_file(json_file)
            if not json_result["valid"]:
                issues.extend([f"JSON: {err}" for err in json_result["errors"]])
            json_structure = json_result.get("data")

            # 检查JS中的数据访问模式
            if json_structure and isinstance(json_structure, dict):
                # 检查JS是否正确访问JSON结构
                if 'papers' in json_structure and 'data.papers' not in open(js_file, 'r', encoding='utf-8').read():
                    issues.append("JS may not correctly access JSON structure (expected 'data.papers')")

        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "html_ids": html_ids,
            "js_used_ids": js_used_ids,
            "missing_ids": missing_ids,
            "json_structure": json_structure
        }

    # ==================== Python文件验证功能 ====================

    def validate_python_file(self, file_path: str, related_files: List[str] = None) -> Dict[str, Any]:
        """
        验证Python文件的全面质量，包括跨文件一致性检查

        Args:
            file_path: 要验证的Python文件路径
            related_files: 相关的Python文件列表，用于跨文件验证

        Returns:
            {
                "valid": bool,
                "syntax_errors": List[str],
                "dependency_issues": List[str],
                "function_issues": List[str],
                "style_issues": List[str],
                "functions": List[Dict],  # 函数分析结果
                "imports": List[str],  # 导入的模块
                "issues": List[str],  # 所有问题的汇总
                "cross_file_issues": List[str],  # 跨文件验证问题
                "module_dependencies": Dict[str, List[str]],  # 模块依赖关系
                "function_calls": List[Dict]  # 跨文件函数调用信息
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {
                "valid": False,
                "syntax_errors": [f"Failed to read file: {str(e)}"],
                "dependency_issues": [],
                "function_issues": [],
                "style_issues": [],
                "functions": [],
                "imports": [],
                "issues": [f"Failed to read file: {str(e)}"]
            }

        syntax_errors = []
        dependency_issues = []
        function_issues = []
        style_issues = []
        issues = []

        # 1. 语法检查
        syntax_result = self.validate_syntax(content, "python")
        if not syntax_result["valid"]:
            syntax_errors.append(syntax_result["error"])
            issues.append(f"Syntax: {syntax_result['error']}")

        # 2. 依赖检查
        dependency_result = self.check_python_dependencies(content, file_path)
        dependency_issues = dependency_result.get("issues", [])
        issues.extend([f"Dependency: {issue}" for issue in dependency_issues])

        # 3. 函数接口分析
        functions_result = self.analyze_python_functions(content, file_path)
        function_issues = functions_result.get("issues", [])
        functions = functions_result.get("functions", [])
        issues.extend([f"Function: {issue}" for issue in function_issues])

        # 4. 代码风格检查（简单检查）
        style_issues = self._check_python_style(content, file_path)
        issues.extend([f"Style: {issue}" for issue in style_issues])

        # 5. 提取导入的模块
        imports = self._extract_python_imports(content)

        # 6. 跨文件验证（如果提供了相关文件）
        cross_file_issues = []
        module_dependencies = {}
        function_calls = []
        
        if related_files and len(related_files) > 0:
            cross_result = self._validate_python_cross_file([file_path] + related_files)
            cross_file_issues = cross_result.get("issues", [])
            module_dependencies = cross_result.get("module_dependencies", {})
            function_calls = cross_result.get("function_calls", [])
            
            # 将跨文件问题添加到总问题列表中
            issues.extend([f"Cross-file: {issue}" for issue in cross_file_issues])

        return {
            "valid": len(issues) == 0,
            "syntax_errors": syntax_errors,
            "dependency_issues": dependency_issues,
            "function_issues": function_issues,
            "style_issues": style_issues,
            "functions": functions,
            "imports": imports,
            "issues": issues,
            "cross_file_issues": cross_file_issues,
            "module_dependencies": module_dependencies,
            "function_calls": function_calls
        }

    def check_python_dependencies(self, content: str, file_path: str) -> Dict[str, Any]:
        """
        检查Python文件的依赖

        Returns:
            {
                "issues": List[str],
                "missing_packages": List[str],
                "relative_imports": List[str]
            }
        """
        issues = []
        missing_packages = []
        relative_imports = []

        # 提取导入的模块
        imports = self._extract_python_imports(content)

        # 检查第三方包
        third_party_packages = []
        for imp in imports:
            # 排除标准库和相对导入
            if not imp.startswith('.') and not self._is_standard_library(imp):
                third_party_packages.append(imp)
            elif imp.startswith('.'):
                relative_imports.append(imp)

        # 检查第三方包是否已安装
        if third_party_packages:
            installed = self.check_installed_packages(third_party_packages)
            for pkg, is_installed in installed.items():
                if not is_installed:
                    missing_packages.append(pkg)
                    issues.append(f"Missing package: {pkg}")

        # 检查相对导入路径
        for rel_import in relative_imports:
            # 简单检查：确保相对导入指向存在的文件
            rel_parts = rel_import.split('.')
            # 移除空字符串和当前目录标识
            rel_parts = [part for part in rel_parts if part]
            
            if rel_parts:
                # 构建相对路径
                file_dir = os.path.dirname(file_path)
                module_name = rel_parts[0]
                
                # 检查相对导入的模块是否存在
                possible_paths = [
                    os.path.join(file_dir, f"{module_name}.py"),
                    os.path.join(file_dir, module_name, "__init__.py")
                ]
                
                if not any(os.path.exists(path) for path in possible_paths):
                    issues.append(f"Relative import may be invalid: {rel_import}")

        return {
            "issues": issues,
            "missing_packages": missing_packages,
            "relative_imports": relative_imports
        }

    def analyze_python_functions(self, content: str, file_path: str) -> Dict[str, Any]:
        """
        分析Python文件中的函数接口

        Returns:
            {
                "functions": List[Dict],
                "issues": List[str]
            }
        """
        functions = []
        issues = []

        # 使用正则表达式查找函数定义
        # 支持: def func(...) -> type: 和 async def func(...):
        func_pattern = r'(async\s+)?def\s+([a-zA-Z_]\w*)\s*\(([^)]*)\)\s*(->\s*[^:]+)?:'
        matches = re.finditer(func_pattern, content, re.MULTILINE)

        for match in matches:
            is_async = bool(match.group(1))
            func_name = match.group(2)
            params_str = match.group(3)
            return_type = match.group(4).strip() if match.group(4) else None

            # 分析参数
            params = []
            if params_str.strip():
                param_list = params_str.split(',')
                for param in param_list:
                    param = param.strip()
                    if param:
                        params.append(param)

            # 检查函数名规范（PEP 8）
            if not func_name.islower() and not func_name.startswith('_'):
                issues.append(f"Function name '{func_name}' should be lowercase with underscores")

            # 检查是否有返回类型注解
            if not return_type and func_name != '__init__':
                issues.append(f"Function '{func_name}' missing return type annotation")

            # 检查参数类型注解
            for param in params:
                if ':' not in param and param not in ('self', 'cls', '*args', '**kwargs'):
                    issues.append(f"Parameter '{param}' in function '{func_name}' missing type annotation")

            # 收集函数信息
            functions.append({
                "name": func_name,
                "is_async": is_async,
                "parameters": params,
                "return_type": return_type,
                "line": content[:match.start()].count('\n') + 1
            })

        # 检查是否有函数定义
        if not functions:
            issues.append("No function definitions found")

        return {
            "functions": functions,
            "issues": issues
        }

    def _validate_python_cross_file(self, python_files: List[str]) -> Dict[str, Any]:
        """
        验证多个Python文件之间的一致性，包括函数接口检查（内部方法）

        Returns:
            {
                "consistent": bool,
                "issues": List[str],
                "module_dependencies": Dict[str, List[str]],
                "function_calls": List[Dict]
            }
        """
        issues = []
        module_dependencies = {}
        function_calls = []

        # 收集所有文件的信息
        file_info = {}
        all_functions = {}
        
        for file_path in python_files:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 提取导入
                imports = self._extract_python_imports(content)
                # 提取函数定义
                func_result = self.analyze_python_functions(content, file_path)
                functions = func_result.get("functions", [])
                
                file_info[file_path] = {
                    "imports": imports,
                    "functions": functions,
                    "content": content
                }
                
                # 构建所有函数的索引（按模块名.函数名）
                module_name = os.path.splitext(os.path.basename(file_path))[0]
                for func in functions:
                    func_key = f"{module_name}.{func['name']}"
                    all_functions[func_key] = {
                        "file_path": file_path,
                        "function": func
                    }

        # 1. 检查模块间的依赖关系
        for file_path, info in file_info.items():
            file_name = os.path.basename(file_path)
            module_name = os.path.splitext(file_name)[0]
            
            module_dependencies[module_name] = []
            
            for imp in info["imports"]:
                # 检查导入的模块是否在文件列表中
                imp_module = imp.split('.')[0]
                found = False
                
                for other_file in python_files:
                    other_module = os.path.splitext(os.path.basename(other_file))[0]
                    if imp_module == other_module:
                        found = True
                        module_dependencies[module_name].append(other_module)
                        break
                
                # 对于相对导入，检查目标文件是否存在
                if imp.startswith('.'):
                    # 简单检查相对导入
                    rel_parts = imp.split('.')
                    rel_parts = [part for part in rel_parts if part]
                    
                    if rel_parts:
                        file_dir = os.path.dirname(file_path)
                        target_module = rel_parts[0]
                        
                        possible_paths = [
                            os.path.join(file_dir, f"{target_module}.py"),
                            os.path.join(file_dir, target_module, "__init__.py")
                        ]
                        
                        if not any(os.path.exists(path) for path in possible_paths):
                            issues.append(f"File {file_path}: Invalid relative import {imp}")
        
        # 2. 提取并检查跨文件函数调用
        for file_path, info in file_info.items():
            module_name = os.path.splitext(os.path.basename(file_path))[0]
            content = info["content"]
            
            # 提取函数调用
            calls = self._extract_function_calls(content, file_path)
            
            for call in calls:
                call_module = call.get("module")
                call_func = call.get("function")
                call_args = call.get("arguments", [])
                call_line = call.get("line")
                
                # 构建可能的函数键
                possible_func_keys = []
                
                if call_module:
                    # 有明确模块的函数调用
                    possible_func_keys.append(f"{call_module}.{call_func}")
                else:
                    # 没有明确模块的函数调用（可能是导入的函数）
                    # 检查所有导入的模块
                    for imp in info["imports"]:
                        imp_module = imp.split('.')[0]
                        possible_func_keys.append(f"{imp_module}.{call_func}")
                    # 检查当前模块
                    possible_func_keys.append(f"{module_name}.{call_func}")
                
                # 查找匹配的函数定义
                matched_func = None
                matched_key = None
                
                for func_key in possible_func_keys:
                    if func_key in all_functions:
                        matched_func = all_functions[func_key]["function"]
                        matched_key = func_key
                        break
                
                if matched_func:
                    # 检查函数调用参数是否与定义匹配
                    call_result = self._check_function_call(matched_func, call_args, call_line, file_path)
                    if call_result.get("issues"):
                        issues.extend(call_result["issues"])
                    
                    # 记录函数调用
                    function_calls.append({
                        "file_path": file_path,
                        "module": call_module,
                        "function": call_func,
                        "arguments": call_args,
                        "matched_function": matched_key,
                        "line": call_line,
                        "valid": len(call_result.get("issues", [])) == 0
                    })
                else:
                    # 没有找到匹配的函数定义
                    issues.append(f"File {file_path} line {call_line}: Function call '{call_func}' from module '{call_module}' has no matching definition")
                    function_calls.append({
                        "file_path": file_path,
                        "module": call_module,
                        "function": call_func,
                        "arguments": call_args,
                        "matched_function": None,
                        "line": call_line,
                        "valid": False
                    })

        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "module_dependencies": module_dependencies,
            "function_calls": function_calls
        }
    
    def _extract_function_calls(self, content: str, file_path: str) -> List[Dict]:
        """
        提取Python代码中的函数调用
        """
        calls = []
        lines = content.split('\n')
        
        # 正则表达式匹配函数调用
        # 只使用一个更精确的模式，避免重复匹配
        call_pattern = r'([a-zA-Z0-9_.]+)\s*\(([^)]*)\)'
        
        for line_num, line in enumerate(lines, 1):
            # 跳过注释行和空行
            if line.strip().startswith('#') or not line.strip():
                continue
            
            # 跳过函数定义行
            if re.match(r'^\s*(async\s+)?def\s+', line):
                continue
            
            # 匹配函数调用
            matches = re.finditer(call_pattern, line)
            for match in matches:
                full_call = match.group(1)
                args_str = match.group(2)
                
                # 解析模块和函数名
                call_parts = full_call.split('.')
                if len(call_parts) > 1:
                    # module.func 或 module.submodule.func
                    module = '.'.join(call_parts[:-1])
                    function = call_parts[-1]
                else:
                    # 直接函数调用
                    module = None
                    function = call_parts[0]
                
                # 解析参数
                arguments = []
                if args_str.strip():
                    arg_list = args_str.split(',')
                    for arg in arg_list:
                        arg = arg.strip()
                        if arg:
                            arguments.append(arg)
                
                # 跳过一些内置函数和方法调用
                skip_functions = ['print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set']
                if function in skip_functions:
                    continue
                
                # 跳过self.method() 或 obj.method()形式的方法调用
                if module and (module == 'self' or module == 'cls' or '.' in module):
                    continue
                
                calls.append({
                    "module": module,
                    "function": function,
                    "arguments": arguments,
                    "line": line_num
                })
        
        return calls
    
    def _check_function_call(self, func_def: Dict, call_args: List[str], call_line: int, file_path: str) -> Dict[str, Any]:
        """
        检查函数调用是否与函数定义匹配
        """
        issues = []
        
        # 获取函数定义的参数
        def_params = func_def.get("parameters", [])
        
        # 计算实际参数数量
        call_arg_count = len(call_args)
        
        # 计算函数定义的参数数量（排除self/cls和*args/**kwargs）
        def_param_count = 0
        has_var_args = False  # *args
        has_kw_var_args = False  # **kwargs
        
        for param in def_params:
            if param in ['self', 'cls']:
                continue
            if param.startswith('*'):
                has_var_args = True
                continue
            if param.startswith('**'):
                has_kw_var_args = True
                continue
            def_param_count += 1
        
        # 检查参数数量是否匹配
        if has_var_args or has_kw_var_args:
            # 如果有*args或**kwargs，可以接受任意数量的参数
            pass
        elif call_arg_count < def_param_count:
            issues.append(f"File {file_path} line {call_line}: Function call missing required arguments. Expected at least {def_param_count}, got {call_arg_count}")
        
        # 检查参数类型（如果有类型注解）
        for i, (def_param, call_arg) in enumerate(zip(def_params, call_args)):
            # 跳过self/cls
            if def_param in ['self', 'cls']:
                continue
            
            # 检查参数是否有类型注解
            if ':' in def_param:
                param_name, param_type = def_param.split(':', 1)
                param_name = param_name.strip()
                param_type = param_type.strip()
                
                # 简单的类型检查（基于参数名或值）
                if call_arg.isdigit():
                    # 数字参数
                    if param_type not in ['int', 'float', 'number', 'Union[int, float]']:
                        issues.append(f"File {file_path} line {call_line}: Argument {i+1} '{param_name}' expected type {param_type}, got int")
                elif call_arg.startswith('"') or call_arg.startswith("'"):
                    # 字符串参数
                    if param_type not in ['str', 'Union[str, int]']:
                        issues.append(f"File {file_path} line {call_line}: Argument {i+1} '{param_name}' expected type {param_type}, got str")
        
        return {
            "issues": issues
        }

    def _extract_python_imports(self, content: str) -> List[str]:
        """
        提取Python代码中的导入模块
        """
        imports = []
        
        # 匹配import语句
        import_pattern = r'^\s*import\s+([a-zA-Z0-9_.]+)'
        from_pattern = r'^\s*from\s+([a-zA-Z0-9_.]+)\s+import'
        
        lines = content.split('\n')
        for line in lines:
            import_match = re.match(import_pattern, line)
            if import_match:
                imports.append(import_match.group(1))
            else:
                from_match = re.match(from_pattern, line)
                if from_match:
                    imports.append(from_match.group(1))
        
        return imports

    def _is_standard_library(self, module_name: str) -> bool:
        """
        简单检查模块是否为Python标准库
        """
        # 常见的标准库模块列表
        standard_libs = {
            'os', 'sys', 'math', 'datetime', 'json', 're', 'subprocess',
            'collections', 'itertools', 'functools', 'random', 'time',
            'logging', 'unittest', 'pytest', 'argparse', 'configparser',
            'csv', 'xml', 'yaml', 'asyncio', 'threading', 'multiprocessing',
            'socket', 'requests', 'urllib', 'http', 'email', 'smtplib',
            'hashlib', 'base64', 'struct', 'pickle', 'copy', 'gc'
        }
        
        # 检查模块名或其根模块是否在标准库中
        module_parts = module_name.split('.')
        return any(part in standard_libs for part in module_parts)

    def _check_python_style(self, content: str, file_path: str) -> List[str]:
        """
        简单的Python代码风格检查
        """
        issues = []
        lines = content.split('\n')
        
        # 检查行长度
        for i, line in enumerate(lines, 1):
            if len(line) > 100:
                issues.append(f"Line {i} is too long ({len(line)} characters > 100)")
        
        # 检查缩进（简单检查：确保使用4个空格）
        for i, line in enumerate(lines, 1):
            if line.startswith('\t'):
                issues.append(f"Line {i} uses tabs instead of spaces")
        
        # 检查空行
        if len(lines) > 0 and lines[0].strip() == '':
            issues.append("File starts with empty line")
        
        return issues
    
    def __del__(self):
        """清理临时目录"""
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except:
            pass  # 忽略清理失败
