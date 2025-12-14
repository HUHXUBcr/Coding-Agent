import json
import time
import os
import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional
from agents.planner import ProjectPlanningAgent
from agents.codegen import CodeGenerationAgent
from agents.evaluator import CodeEvaluationAgent
from tools.filesystem import FileSystemTool
from tools.web_search import BraveSearchTool  
from tools.code_executor import CodeExecutionTool  
from tools.code_knowledge_base import CodeKnowledgeBase, code_knowledge_base
from dotenv import load_dotenv

load_dotenv()

class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentType(Enum):
    """智能体类型枚举"""
    PLANNER = "planner"
    CODEGEN = "codegen"
    EVALUATOR = "evaluator"


class Orchestrator:
    """
    多智能体协作编排器
    实现任务调度、通信管理和状态管理的核心功能
    """
    
    # 统一的质量控制常量
    TARGET_QUALITY_SCORE = 0.7
    MAX_FIX_ATTEMPTS = 5
    
    def __init__(self, output_dir='output', llm_api_key=None, llm_model=None):
        # 加载API密钥
        api_key = llm_api_key or os.getenv('DASHSCOPE_API_KEY')
        if not api_key:
            raise ValueError("未找到API密钥。请确保.env文件中包含DASHSCOPE_API_KEY=your_api_key!")
        
        self.fs = FileSystemTool(base_dir=output_dir)
        self.web_search = BraveSearchTool()  # 启用web_search
        self.code_executor = CodeExecutionTool()  # 启用code_executor
        
        # 代码知识库初始化
        self.code_knowledge_base = code_knowledge_base

        # Agents 的工具配置
        self.planner = ProjectPlanningAgent(api_key=api_key)
        self.planner.tools = {'web_search': self.web_search}  

        self.codegen = CodeGenerationAgent(api_key=api_key, code_knowledge_base=self.code_knowledge_base)
        self.codegen.tools = {'web_search': self.web_search}  

        self.evaluator = CodeEvaluationAgent(self.fs, api_key=api_key)
        self.evaluator.tools = {'code_executor': self.code_executor, 'web_search': self.web_search}

        # 用于状态管理的增强型内存结构
        self.memory = {
            'project_state': {
                'start_time': None,
                'end_time': None,
                'overall_status': 'not_started',
                'current_task_index': 0,
                'progress_percentage': 0.0,
                'estimated_remaining_time': None,
                'current_phase': 'initialization',
                'resource_usage': {
                    'memory_mb': 0,
                    'cpu_percent': 0,
                    'disk_usage_mb': 0
                }
            },
            'task_history': [],  # 记录所有执行过的任务
            'agent_communications': [],  # 智能体间通信记录
            'file_dependencies': {},  # 文件依赖关系
            'error_logs': [],  # 错误日志
            'performance_metrics': {
                'total_execution_time': 0.0,
                'agent_performance': {
                    'planner': {'calls': 0, 'avg_time': 0.0},
                    'codegen': {'calls': 0, 'avg_time': 0.0},
                    'evaluator': {'calls': 0, 'avg_time': 0.0}
                },
                'throughput': {'tasks_per_minute': 0.0},
                'quality_metrics': {
                    'code_quality_score': 0.0,
                    'error_rate': 0.0,
                    'success_rate': 0.0
                }
            },
            'shared_context': {
                'global_variables': {},
                'shared_knowledge': [],
                'decision_log': [],
                'constraints': {}
            },
            'version_control': {
                'file_versions': {},
                'change_history': []
            }
        }
        
        # 任务调度队列
        self.task_queue = []
        
        # 通信协议
        self.communication_protocols = {
            'planner_to_codegen': self._planner_to_codegen_protocol,
            'codegen_to_evaluator': self._codegen_to_evaluator_protocol,
            'evaluator_to_codegen': self._evaluator_to_codegen_protocol
        }

    def _planner_to_codegen_protocol(self, plan_data: Dict, file_info: Dict) -> Dict:
        """Planner到Codegen的通信协议"""
        # 生成代码知识库上下文
        file_path = file_info.get('file_path', '')
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # 根据文件类型生成不同的上下文
        if file_ext in ['.py']:
            # Python文件：生成导入上下文
            code_context = self.code_knowledge_base.generate_import_context(file_path)
        elif file_ext in ['.html', '.css', '.js']:
            # Web文件：生成项目结构上下文和路径建议
            code_context = self.code_knowledge_base.generate_web_file_context(file_path)
        else:
            # 其他文件类型：生成基本结构上下文
            code_context = self.code_knowledge_base.get_project_structure_summary()
        
        return {
            'message_type': 'task_assignment',
            'plan_context': plan_data,
            'file_spec': file_info,
            'code_knowledge_context': code_context,  # 添加代码知识库上下文
            'priority': 'high',
            'deadline': None,  
            'timestamp': datetime.now().isoformat(),
            'protocol_version': '1.0',
            'metadata': {
                'source_agent': 'planner',
                'target_agent': 'codegen',
                'communication_id': f"comm_{int(time.time()*1000)}"
            }
        }

    def _codegen_to_evaluator_protocol(self, file_path: str, content: str) -> Dict:
        """Codegen到Evaluator的通信协议"""
        return {
            'message_type': 'code_submission',
            'file_path': file_path,
            'content_preview': content[:200] + '...' if len(content) > 200 else content,
            'content_length': len(content),
            'language': self._detect_language(file_path),
            'quality_metrics': self._calculate_code_metrics(content),
            'timestamp': datetime.now().isoformat(),
            'protocol_version': '1.0',
            'metadata': {
                'source_agent': 'codegen',
                'target_agent': 'evaluator',
                'communication_id': f"comm_{int(time.time()*1000)}"
            }
        }

    def _evaluator_to_codegen_protocol(self, review_result: Dict, original_content: str) -> Dict:
        """Evaluator到Codegen的通信协议"""
        return {
            'message_type': 'review_feedback',
            'review_result': review_result,
            'original_content_preview': original_content[:200] + '...' if len(original_content) > 200 else original_content,
            'fix_required': not review_result.get('ok', False),
            'suggested_changes': review_result.get('notes', []),
            'severity_level': self._determine_severity(review_result),
            'timestamp': datetime.now().isoformat(),
            'protocol_version': '1.0',
            'metadata': {
                'source_agent': 'evaluator',
                'target_agent': 'codegen',
                'communication_id': f"comm_{int(time.time()*1000)}"
            }
        }

    def _detect_language(self, file_path: str) -> str:
        """检测文件编程语言"""
        extension_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'c++',
            '.c': 'c',
            '.go': 'go',
            '.rs': 'rust',
            '.html': 'html',
            '.css': 'css',
            '.json': 'json'
        }
        for ext, lang in extension_map.items():
            if file_path.endswith(ext):
                return lang
        return 'unknown'
    
    def _sort_files_by_dependency(self, files: List[Dict]) -> List[Dict]:
        """按依赖关系排序文件: data -> logic -> style -> view -> entry_point"""
        priority = {
            'data': 0,
            'logic': 1,
            'style': 2,
            'view': 3,
            'entry_point': 4,
        }
        return sorted(files, key=lambda f: priority.get(f.get('role', 'view'), 99))

    def _calculate_code_metrics(self, content: str) -> Dict:
        """计算代码质量指标"""
        lines = content.split('\n')
        return {
            'line_count': len(lines),
            'non_empty_lines': len([l for l in lines if l.strip()]),
            'avg_line_length': sum(len(l) for l in lines) / len(lines) if lines else 0,
            'complexity_estimate': len([l for l in lines if any(keyword in l for keyword in ['if', 'for', 'while', 'def', 'class'])]) / len(lines) if lines else 0
        }

    def _determine_severity(self, review_result: Dict) -> str:
        """确定问题严重级别"""
        notes = review_result.get('notes', '').lower()
        if any(keyword in notes for keyword in ['critical', 'error', 'fatal', 'broken']):
            return 'critical'
        elif any(keyword in notes for keyword in ['warning', 'issue', 'problem']):
            return 'warning'
        elif any(keyword in notes for keyword in ['suggestion', 'improvement', 'enhancement']):
            return 'suggestion'
        else:
            return 'info'

    def _update_project_state(self, key: str, value: Any):
        """更新项目状态"""
        self.memory['project_state'][key] = value
        self._log_state_change(f"Project state updated: {key} = {value}")

    def _log_communication(self, from_agent: AgentType, to_agent: AgentType, message: Dict):
        """记录智能体间通信"""
        communication_record = {
            'from': from_agent.value,
            'to': to_agent.value,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        self.memory['agent_communications'].append(communication_record)
        self._log_state_change(f"Communication: {from_agent.value} -> {to_agent.value}")

    def _log_task_execution(self, task_id: str, agent: AgentType, status: TaskStatus, result: Any = None):
        """记录任务执行历史"""
        task_record = {
            'task_id': task_id,
            'agent': agent.value,
            'status': status.value,
            'result': result,
            'timestamp': datetime.now().isoformat(),
            'execution_time': time.time()
        }
        self.memory['task_history'].append(task_record)
        self._log_state_change(f"Task {task_id} executed by {agent.value}: {status.value}")

    def _log_state_change(self, message: str):
        """记录状态变化"""
        print(f"[Orchestrator State] {message}")

    def _update_performance_metrics(self, agent_name: str, execution_time: float):
        """更新性能指标"""
        agent_metrics = self.memory['performance_metrics']['agent_performance'][agent_name]
        agent_metrics['calls'] += 1
        agent_metrics['avg_time'] = (
            (agent_metrics['avg_time'] * (agent_metrics['calls'] - 1) + execution_time) / 
            agent_metrics['calls']
        )

    def _update_progress(self):
        """更新进度信息"""
        total_tasks = len(self.memory['task_history'])
        completed_tasks = len([t for t in self.memory['task_history'] 
                             if t['status'] == TaskStatus.COMPLETED.value])
        
        if total_tasks > 0:
            progress = (completed_tasks / total_tasks) * 100
            self.memory['project_state']['progress_percentage'] = progress
            
            # 简单的剩余时间估算
            if progress > 0:
                elapsed_time = time.time() - self._get_start_timestamp()
                estimated_total_time = elapsed_time / (progress / 100)
                remaining_time = estimated_total_time - elapsed_time
                self.memory['project_state']['estimated_remaining_time'] = remaining_time

    def _get_start_timestamp(self) -> float:
        """获取开始时间戳"""
        start_time_str = self.memory['project_state']['start_time']
        if start_time_str:
            dt = datetime.fromisoformat(start_time_str)
            return dt.timestamp()
        return time.time()

    def _update_shared_context(self, key: str, value: Any, source: str = 'system'):
        """更新共享上下文"""
        self.memory['shared_context']['global_variables'][key] = value
        
        # 记录决策日志
        decision_record = {
            'key': key,
            'value': value,
            'source': source,
            'timestamp': datetime.now().isoformat()
        }
        self.memory['shared_context']['decision_log'].append(decision_record)

    def _track_file_version(self, file_path: str, content: str, operation: str):
        """跟踪文件版本"""
        if file_path not in self.memory['version_control']['file_versions']:
            self.memory['version_control']['file_versions'][file_path] = []
        
        version_record = {
            'version_id': len(self.memory['version_control']['file_versions'][file_path]) + 1,
            'content_hash': hash(content),
            'operation': operation,
            'timestamp': datetime.now().isoformat(),
            'size_bytes': len(content.encode('utf-8'))
        }
        self.memory['version_control']['file_versions'][file_path].append(version_record)
        
        # 记录变更历史
        self.memory['version_control']['change_history'].append({
            'file_path': file_path,
            'version_id': version_record['version_id'],
            'timestamp': version_record['timestamp']
        })

    def get_project_status(self) -> Dict:
        """获取项目状态摘要"""
        return {
            'overall_status': self.memory['project_state']['overall_status'],
            'progress': self.memory['project_state']['progress_percentage'],
            'current_phase': self.memory['project_state']['current_phase'],
            'tasks_completed': len([t for t in self.memory['task_history'] 
                                  if t['status'] == TaskStatus.COMPLETED.value]),
            'total_tasks': len(self.memory['task_history']),
            'errors_count': len(self.memory['error_logs']),
            'communications_count': len(self.memory['agent_communications'])
        }

    def export_memory_snapshot(self) -> Dict:
        """导出内存快照"""
        return {
            'timestamp': datetime.now().isoformat(),
            'project_state': self.memory['project_state'],
            'performance_metrics': self.memory['performance_metrics'],
            'task_summary': {
                'total': len(self.memory['task_history']),
                'completed': len([t for t in self.memory['task_history'] 
                                if t['status'] == TaskStatus.COMPLETED.value]),
                'failed': len([t for t in self.memory['task_history'] 
                             if t['status'] == TaskStatus.FAILED.value])
            },
            'communication_summary': {
                'total': len(self.memory['agent_communications']),
                'by_agent': self._summarize_communications()
            }
        }

    def _summarize_communications(self) -> Dict:
        """总结通信记录"""
        summary = {}
        for comm in self.memory['agent_communications']:
            key = f"{comm['from']}_to_{comm['to']}"
            summary[key] = summary.get(key, 0) + 1
        return summary

    def _update_error_metrics(self):
        """更新错误率指标"""
        total_tasks = len(self.memory['task_history'])
        failed_tasks = len([t for t in self.memory['task_history'] 
                          if t['status'] == TaskStatus.FAILED.value])
        
        if total_tasks > 0:
            error_rate = (failed_tasks / total_tasks) * 100
            success_rate = 100 - error_rate
            
            self.memory['performance_metrics']['quality_metrics']['error_rate'] = error_rate
            self.memory['performance_metrics']['quality_metrics']['success_rate'] = success_rate
            
            # 计算代码质量分数（基于错误率和成功率的综合评分）
            quality_score = max(0, 100 - (error_rate * 2))  # 错误率权重加倍
            self.memory['performance_metrics']['quality_metrics']['code_quality_score'] = quality_score

    def _calculate_throughput(self):
        """计算吞吐量指标"""
        if self.memory['project_state']['start_time'] and self.memory['project_state']['end_time']:
            start_dt = datetime.fromisoformat(self.memory['project_state']['start_time'])
            end_dt = datetime.fromisoformat(self.memory['project_state']['end_time'])
            duration_minutes = (end_dt - start_dt).total_seconds() / 60
            
            if duration_minutes > 0:
                tasks_per_minute = len(self.memory['task_history']) / duration_minutes
                self.memory['performance_metrics']['throughput']['tasks_per_minute'] = tasks_per_minute
    
    def _is_standard_library(self, module_name: str) -> bool:
        """
        检查模块是否为Python标准库
        
        Args:
            module_name: 模块名称
            
        Returns:
            是否为标准库
        """
        import sys
        # 内置模块检查
        builtin_modules = set(sys.builtin_module_names)
        if module_name in builtin_modules:
            return True
        
        # 常见标准库列表
        standard_lib = {
            'os', 'sys', 're', 'math', 'datetime', 'json', 'csv', 'xml', 'html',
            'urllib', 'http', 'socket', 'threading', 'asyncio', 'multiprocessing',
            'logging', 'configparser', 'argparse', 'subprocess', 'io', 'tempfile',
            'pathlib', 'shutil', 'stat', 'glob', 'fnmatch', 'collections', 'itertools',
            'functools', 'operator', 'heapq', 'bisect', 'array', 'types', 'typing',
            'dataclasses', 'enum', 'contextlib', 'abc', 'numbers', 'decimal', 'fractions',
            'random', 'secrets', 'hashlib', 'hmac', 'base64', 'binascii', 'struct',
            'pickle', 'shelve', 'marshal', 'copy', 'weakref', 'gc', 'inspect', 'ast',
            'dis', 'traceback', 'pdb', 'code', 'codeop', 'compileall', 'py_compile',
            'imp', 'importlib', 'zipimport', 'pkgutil', 'pkg_resources', 'modulefinder',
            'runpy', 'site', 'venv', 'distutils', 'ensurepip', 'setuptools',
            'warnings', 'contextvars', 'typing_extensions', 'zoneinfo'
        }
        
        return module_name in standard_lib or module_name.startswith(('__', 'builtins'))
    
    def _generate_requirements_txt(self):
        """
        根据生成的Python文件内容生成requirements.txt文件
        """
        # 收集所有生成的Python文件
        python_files = []
        for root, _, files in os.walk(self.fs.base_dir):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    python_files.append(file_path)
        
        if not python_files:
            print(f"[Orchestrator] No Python files found, skipping requirements.txt generation")
            return
        
        # 提取第三方依赖
        third_party_dependencies = set()
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 分析导入语句
                for line in content.split('\n'):
                    line = line.strip()
                    # 跳过空行和注释
                    if not line or line.startswith('#'):
                        continue
                    
                    # 处理import语句
                    if line.startswith('import '):
                        # 格式：import module
                        # 或：import module as alias
                        # 或：import module.submodule
                        parts = line.split(' ')
                        if len(parts) >= 2:
                            module_part = parts[1].split('.')[0]  # 只取主模块名
                            third_party_dependencies.add(module_part)
                    
                    # 处理from语句
                    elif line.startswith('from '):
                        # 格式：from module import something
                        # 或：from module.submodule import something
                        # 或：from module import *
                        parts = line.split(' ')
                        if len(parts) >= 3 and parts[2] == 'import':
                            module_part = parts[1].split('.')[0]  # 只取主模块名
                            third_party_dependencies.add(module_part)
                            
            except Exception as e:
                print(f"[Orchestrator] Error processing {file_path} for requirements.txt: {e}")
        
        # 过滤出第三方依赖，排除标准库和相对导入
        final_dependencies = set()
        for module in third_party_dependencies:
            # 排除相对导入（以.开头）和标准库
            if not module.startswith('.') and not self._is_standard_library(module):
                final_dependencies.add(module)
        
        # 生成requirements.txt文件
        if final_dependencies:
            requirements_path = os.path.join(self.fs.base_dir, 'requirements.txt')
            with open(requirements_path, 'w', encoding='utf-8') as f:
                for dependency in sorted(final_dependencies):
                    f.write(f"{dependency}\n")
            print(f"[Orchestrator] Generated requirements.txt with {len(final_dependencies)} dependencies")
        else:
            print(f"[Orchestrator] No third-party dependencies found, skipping requirements.txt")

    def _schedule_next_task(self, current_task_result: Any = None) -> Optional[Dict]:
        """智能任务调度：决定下一个执行的任务"""
        if not self.task_queue:
            return None
        
        # 简单的先进先出调度策略
        next_task = self.task_queue.pop(0)
        
        # 检查任务依赖关系
        dependencies = next_task.get('dependencies', [])
        for dep in dependencies:
            dep_task = next((t for t in self.memory['task_history'] if t['task_id'] == dep), None)
            if not dep_task or dep_task['status'] != TaskStatus.COMPLETED.value:
                # 依赖任务未完成，重新排队
                self.task_queue.append(next_task)
                return None
        
        return next_task

    def _determine_task_completion(self) -> bool:
        """确定任务完成状态"""
        # 检查所有任务是否完成
        completed_tasks = [t for t in self.memory['task_history'] 
                         if t['status'] == TaskStatus.COMPLETED.value]
        failed_tasks = [t for t in self.memory['task_history'] 
                       if t['status'] == TaskStatus.FAILED.value]
        
        total_tasks = len(self.memory['task_history'])
        
        if failed_tasks:
            self._update_project_state('overall_status', 'failed')
            return True
        
        if len(completed_tasks) == total_tasks and total_tasks > 0:
            self._update_project_state('overall_status', 'completed')
            return True
        
        return False

    def run(self, user_task: str):
        """执行多智能体协作流程"""
        # 初始化项目状态并保存原始任务
        self.memory['original_user_task'] = user_task
        self._update_project_state('start_time', datetime.now().isoformat())
        self._update_project_state('overall_status', 'in_progress')
        self._update_project_state('current_phase', 'planning')
        
        print('[Orchestrator] Received task:')
        print(user_task)

        # 阶段1: 规划阶段
        self._log_state_change("Starting planning phase")
        start_time = time.time()
        plan = self.planner.plan(user_task)
        execution_time = time.time() - start_time
        
        self._update_performance_metrics('planner', execution_time)
        self._log_task_execution('planning_phase', AgentType.PLANNER, TaskStatus.COMPLETED, plan)
        
        # 构建任务队列
        if isinstance(plan, dict) and 'task_list' in plan:
            for i, task_data in enumerate(plan['task_list']):
                task_id = f"task_{i+1}"
                # 按依赖顺序排序文件：data -> logic -> style -> view
                sorted_files = self._sort_files_by_dependency(task_data.get('files', []))
                task_item = {
                    'task_id': task_id,
                    'description': task_data['task'],
                    'files': sorted_files,
                    'dependencies': [],  
                    'agent': AgentType.CODEGEN
                }
                self.task_queue.append(task_item)
                
                print(f" {i+1}. {task_data['task']} -> files: {sorted_files}")
        
        # 阶段2: 执行任务队列
        self._log_state_change("Starting execution phase")
        self._update_project_state('current_phase', 'execution')
        
        while self.task_queue:
            current_task = self._schedule_next_task()
            if not current_task:
                continue
            
            # 执行当前任务
            for file_info in current_task['files']:
                try:
                    # 通信管理: Planner -> Codegen
                    comm_message = self._planner_to_codegen_protocol(plan, file_info)
                    self._log_communication(AgentType.PLANNER, AgentType.CODEGEN, comm_message)
                    
                    # 代码生成 - 传递完整上下文包括用户原始任务
                    path = self.fs.resolve(file_info['path'])
                    codegen_start = time.time()
                    enhanced_context = plan.copy() if isinstance(plan, dict) else {'plan': plan}
                    enhanced_context['task_description'] = self.memory.get('original_user_task', '')
                    content = self.codegen.generate(file_info, context=enhanced_context)
                    codegen_time = time.time() - codegen_start
                    
                    self._update_performance_metrics('codegen', codegen_time)
                    
                    # 写入文件并验证其已写入
                    self.fs.write_file(path, content)
                    self._track_file_version(path, content, 'create')
                    print(f"[Orchestrator] Wrote {path} ({len(content)} bytes)")
                    
                    # 获取文件扩展名
                    file_ext = os.path.splitext(path)[1].lower()
                    
                    # 更新代码知识库 - 将新生成的文件添加到知识库中
                    try:
                        if file_ext == '.py':
                            # Python文件：使用add_module方法
                            self.code_knowledge_base.add_module(path, content)
                            print(f"[Orchestrator] Updated code knowledge base with Python file: {path}")
                        elif file_ext in ['.html', '.css', '.js']:
                            # Web文件：使用add_web_file方法
                            self.code_knowledge_base.add_web_file(path, content)
                            print(f"[Orchestrator] Updated code knowledge base with Web file: {path}")
                        else:
                            # 其他文件类型：记录但不添加到知识库
                            print(f"[Orchestrator] File type {file_ext} not added to code knowledge base: {path}")
                    except Exception as kb_error:
                        print(f"[Orchestrator] Warning: Failed to update code knowledge base for {path}: {kb_error}")
                    
                    # 如果内容为空则跳过评估
                    if not content or len(content.strip()) < 10:
                        print(f"[Orchestrator] Warning: Generated content is empty or too short for {path}")
                        self._log_task_execution(current_task['task_id'], current_task['agent'], TaskStatus.FAILED, "Empty content generated")
                        continue
                    
                    # 通信管理: Codegen -> Evaluator
                    eval_comm = self._codegen_to_evaluator_protocol(path, content)
                    self._log_communication(AgentType.CODEGEN, AgentType.EVALUATOR, eval_comm)
                    
                    # 代码评估 - 只进行一次,避免过度严格
                    eval_start = time.time()
                    
                    # 对不同类型的文件进行额外验证
                    validation_result = None
                    
                    if file_ext in ['.html', '.js', '.css', '.json']:
                        # 对Web文件进行验证
                        # 查找相关文件
                        related_files = self._find_related_web_files(path, plan.get('task_list', []))
                        # 构建文件路径列表进行验证
                        files_to_validate = [path]
                        if related_files:
                            files_to_validate.extend(related_files.values())
                        validation_result = self.evaluator.validate_web_files(files_to_validate)
                        
                        if not validation_result.get('valid', True):
                            print(f"[Orchestrator] Web file validation found issues in {path}:")
                            for error in validation_result.get('errors', []):
                                print(f"  ERROR: {error}")
                            for warning in validation_result.get('warnings', []):
                                print(f"  WARNING: {warning}")
                    elif file_ext == '.py':
                        # 对Python文件进行验证
                        validation_result = self.code_executor.validate_python_file(path)
                        
                        if not validation_result.get('valid', True):
                            print(f"[Orchestrator] Python file validation found issues in {path}:")
                            for issue in validation_result.get('issues', []):
                                print(f"  ISSUE: {issue}")
                    
                    review = self.evaluator.review(path)
                    
                    # 将验证结果整合到review中
                    if validation_result and not validation_result.get('valid', True):
                        review['ok'] = False
                        review['quality_score'] = review.get('quality_score', 0.8)
                        if 'notes' not in review:
                            review['notes'] = ''
                        
                        if file_ext == '.py':
                            # 整合Python验证结果
                            review['notes'] += f" Python validation issues: {'; '.join(validation_result.get('issues', []))}"
                            # 将Python验证详细结果添加到review中
                            review['python_validation'] = validation_result
                        else:
                            # 整合Web验证结果
                            review['notes'] += f" Web validation errors: {'; '.join(validation_result.get('errors', []))}"
                    
                    eval_time = time.time() - eval_start
                    
                    self._update_performance_metrics('evaluator', eval_time)
                    
                    quality_score = review.get('quality_score', 0)
                    
                    # 修复代码
                    if not review['ok']:
                        # 获取评估信息（code_executor notes + LLM evaluation）
                        notes = review.get('notes', '')
                        evaluation_info = review['evaluation']
                        notes = ", ".join([f"{k}: {v}" for k, v in evaluation_info.items()])
                        
                        print(f"[Orchestrator] Evaluator requested changes: {notes}")
                        print(f"[Orchestrator] Quality score: {quality_score} (ok={review['ok']}) - attempting fix")
                        
                        # 通信管理: Evaluator -> Codegen
                        fix_comm = self._evaluator_to_codegen_protocol(review, content)
                        self._log_communication(AgentType.EVALUATOR, AgentType.CODEGEN, fix_comm)
                        
                        # 代码修复 - 持续修复直到达到目标分数或最大尝试次数
                        fixed_content = content
                        best_content = content
                        best_score = quality_score
                        
                        for fix_attempt in range(self.MAX_FIX_ATTEMPTS):
                            try:
                                fix_start = time.time()
                                print(f"[Orchestrator] Fix attempt {fix_attempt+1}/{self.MAX_FIX_ATTEMPTS} for {path} (current score: {best_score:.2f}, target: {self.TARGET_QUALITY_SCORE})")
                                
                                fixed = self.codegen.fix(fixed_content, review)
                                fix_time = time.time() - fix_start
                                
                                self._update_performance_metrics('codegen', fix_time)
                                
                                # 检查修复是否产生有效内容
                                if not fixed:
                                    print(f"[Orchestrator] Fix attempt {fix_attempt+1} produced insufficient content, retrying with original...")
                                    # 如果修复失败，重新用原始内容和更详细的错误信息再试
                                    if fix_attempt < self.MAX_FIX_ATTEMPTS - 1:
                                        fixed_content = content  # 重置为原始内容
                                        review['notes'] = review.get('notes', '') + f" [Previous fix attempt failed to generate valid content]"
                                        continue
                                    else:
                                        print(f"[Orchestrator] All fix attempts produced invalid content, keeping best version (score: {best_score:.2f})")
                                        break
                                
                                # Re-evaluate the fixed version
                                self.fs.write_file(path, fixed)
                                self._track_file_version(path, fixed, f'fix_attempt_{fix_attempt+1}')
                                
                                # 更新代码知识库 - 修复后的文件也要更新知识库
                                try:
                                    if file_ext == '.py':
                                        # Python文件：使用add_module方法
                                        self.code_knowledge_base.add_module(path, fixed)
                                        print(f"[Orchestrator] Updated code knowledge base with fixed Python file: {path}")
                                    elif file_ext in ['.html', '.css', '.js']:
                                        # Web文件：使用add_web_file方法
                                        self.code_knowledge_base.add_web_file(path, fixed)
                                        print(f"[Orchestrator] Updated code knowledge base with fixed Web file: {path}")
                                except Exception as kb_error:
                                    print(f"[Orchestrator] Warning: Failed to update code knowledge base for fixed {path}: {kb_error}")
                                
                                # Quick re-evaluation
                                reeval = self.evaluator.review(path)
                                new_score = reeval.get('quality_score', 0)
                                
                                print(f"[Orchestrator] Fix attempt {fix_attempt+1} score: {new_score:.2f} (was: {best_score:.2f})")
                                
                                # 更新最佳版本
                                if new_score > best_score:
                                    best_content = fixed
                                    best_score = new_score
                                    print(f"[Orchestrator] New best version for {path} (score improved to {best_score:.2f})")
                                
                                # 检查是否达到目标分数
                                if new_score >= self.TARGET_QUALITY_SCORE:
                                    print(f"[Orchestrator] Target score reached! {path} score: {new_score:.2f} >= {self.TARGET_QUALITY_SCORE}")
                                    fixed_content = fixed
                                    break
                                elif fix_attempt < self.MAX_FIX_ATTEMPTS - 1:
                                    # 继续修复，使用新的评估结果
                                    print(f"[Orchestrator] Score {new_score:.2f} below target {self.TARGET_QUALITY_SCORE}, continuing fixes...")
                                    fixed_content = fixed
                                    review = reeval  
                                else:
                                    # 最后一次尝试，保留最佳版本
                                    print(f"[Orchestrator] Max attempts reached. Using best version with score {best_score:.2f}")
                                    if best_content != fixed:
                                        self.fs.write_file(path, best_content)
                                        self._track_file_version(path, best_content, 'final_best')
                                        
                                        # 更新代码知识库 - 最终最佳版本也要更新知识库
                                        try:
                                            if file_ext == '.py':
                                                # Python文件：使用add_module方法
                                                self.code_knowledge_base.add_module(path, best_content)
                                                print(f"[Orchestrator] Updated code knowledge base with final best Python file: {path}")
                                            elif file_ext in ['.html', '.css', '.js']:
                                                # Web文件：使用add_web_file方法
                                                self.code_knowledge_base.add_web_file(path, best_content)
                                                print(f"[Orchestrator] Updated code knowledge base with final best Web file: {path}")
                                        except Exception as kb_error:
                                            print(f"[Orchestrator] Warning: Failed to update code knowledge base for final best {path}: {kb_error}")
                                
                                # 记录修复任务
                                self._log_task_execution(f"fix_{current_task['task_id']}_attempt_{fix_attempt+1}", AgentType.CODEGEN, TaskStatus.COMPLETED)
                                
                            except Exception as fix_error:
                                print(f"[Orchestrator] Fix attempt {fix_attempt+1} failed for {path}: {fix_error}")
                                if fix_attempt == self.MAX_FIX_ATTEMPTS - 1:
                                    print(f"[Orchestrator] All fix attempts failed, keeping original")
                                    self.fs.write_file(path, content)
                                    
                                    # 更新代码知识库 - 修复失败时保留原始内容也要更新知识库
                                    try:
                                        if file_ext == '.py':
                                            # Python文件：使用add_module方法
                                            self.code_knowledge_base.add_module(path, content)
                                            print(f"[Orchestrator] Updated code knowledge base with original Python file: {path} (fix failed)")
                                        elif file_ext in ['.html', '.css', '.js']:
                                            # Web文件：使用add_web_file方法
                                            self.code_knowledge_base.add_web_file(path, content)
                                            print(f"[Orchestrator] Updated code knowledge base with original Web file: {path} (fix failed)")
                                    except Exception as kb_error:
                                        print(f"[Orchestrator] Warning: Failed to update code knowledge base for original {path}: {kb_error}")
                    
                    elif quality_score >= 0.5:
                        print(f"[Orchestrator] Quality score {quality_score} is acceptable for {path}")
                    
                    # 记录任务完成 - 文件已成功生成
                    self._log_task_execution(current_task['task_id'], current_task['agent'], TaskStatus.COMPLETED)
                    
                    # 验证文件引用关系
                    if file_ext in ['.html', '.js', '.css', '.json']:
                        related_files = self._find_related_web_files(path, plan.get('task_list', []))
                        ref_result = self._validate_file_references(path, related_files)
                        
                        if not ref_result["valid"] or ref_result["warnings"]:
                            print(f"[Orchestrator] 文件引用验证 - {path}: {json.dumps(ref_result, indent=2, ensure_ascii=False)}")
                            
                            # 如果引用关系有严重问题，可能需要重新生成
                            if not ref_result["valid"]:
                                print(f"[Orchestrator] 文件引用关系验证失败，可能需要重新生成: {path}")
                                # 记录错误但继续执行，不中断流程
                                error_record = {
                                    'task_id': current_task['task_id'],
                                    'error': f"文件引用关系验证失败: {ref_result['errors']}",
                                    'timestamp': datetime.now().isoformat()
                                }
                                self.memory['error_logs'].append(error_record)
                    
                    # 更新进度
                    self._update_progress()
                    
                except Exception as e:
                    # 错误处理
                    error_record = {
                        'task_id': current_task['task_id'],
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    }
                    self.memory['error_logs'].append(error_record)
                    self._log_task_execution(current_task['task_id'], current_task['agent'], TaskStatus.FAILED, str(e))
                    print(f"[Orchestrator] Task {current_task['task_id']} failed: {e}")
                    
                    # 更新错误率指标
                    self._update_error_metrics()
        
        # 阶段3: 完成处理
        self._update_project_state('end_time', datetime.now().isoformat())
        self._update_project_state('current_phase', 'completion')
        
        # 计算最终性能指标
        self._calculate_throughput()
        self._update_error_metrics()
        
        # 生成requirements.txt文件
        self._generate_requirements_txt()
        
        # 确定最终完成状态
        if self._determine_task_completion():
            print(f'[Orchestrator] All tasks completed. Output written to {self.fs.base_dir}')
            print(f'[Orchestrator] Project status: {self.memory["project_state"]["overall_status"]}')
        else:
            print('[Orchestrator] Some tasks may have failed. Check error logs.')
    
    def _find_related_web_files(self, current_file: str, task_list: List[Dict]) -> Dict[str, str]:
        """
        查找与当前文件相关的其他Web文件
        返回相关文件字典，如 {"html": "index.html", "js": "main.js"}
        
        改进：基于文件角色和命名约定智能匹配相关文件
        """
        related = {}
        current_ext = os.path.splitext(current_file)[1].lower()
        current_dir = os.path.dirname(current_file)
        current_base = os.path.basename(current_file).replace(current_ext, '')
        
        # 根据文件角色和命名约定智能匹配
        for task in task_list:
            task_path = task.get('path', '')
            task_role = task.get('role', '')
            if not task_path or task_path == current_file:
                continue
            
            task_ext = os.path.splitext(task_path)[1].lower()
            task_dir = os.path.dirname(task_path)
            task_base = os.path.basename(task_path).replace(task_ext, '')
            
            # 智能匹配规则：
            # 1. 同目录或相邻目录
            # 2. 同名不同扩展名
            # 3. 基于文件角色的逻辑关联
            # 4. 基于命名约定的关联（如index.html对应index.js）
            
            is_related = (
                task_dir == current_dir or  # 同目录
                task_dir.startswith(current_dir) or  # 子目录
                current_dir.startswith(task_dir) or  # 父目录
                task_base == current_base or  # 同名不同扩展名
                self._is_logically_related(current_base, task_base, current_ext, task_ext, task_role)  # 逻辑关联
            )
            
            if is_related:
                if task_ext == '.html':
                    related['html'] = task_path
                elif task_ext == '.js':
                    related['js'] = task_path
                elif task_ext == '.css':
                    related['css'] = task_path
                elif task_ext == '.json':
                    related['json'] = task_path
        
        return related
    
    def _is_logically_related(self, current_base: str, task_base: str, current_ext: str, task_ext: str, task_role: str) -> bool:
        """
        判断文件间是否存在逻辑关联
        """
        # 基于文件角色的逻辑关联
        if task_role in ['main', 'index', 'app'] and current_ext == '.js':
            # JS文件与主HTML文件关联
            return task_base in ['index', 'main', 'app'] and task_ext == '.html'
        
        # 基于命名约定的关联
        if current_ext == '.html' and task_ext == '.js':
            # HTML文件与对应的JS文件关联（如index.html对应index.js）
            return task_base == current_base
        
        if current_ext == '.html' and task_ext == '.css':
            # HTML文件与对应的CSS文件关联
            return task_base in ['style', 'styles', 'main'] or task_base == current_base
        
        if current_ext == '.js' and task_ext == '.json':
            # JS文件与数据文件关联
            return task_base in ['data', 'config', 'settings'] or 'data' in task_role.lower()
        
        return False
    
    def _validate_file_references(self, file_path: str, related_files: Dict[str, str]) -> Dict[str, Any]:
        """
        验证文件间的引用关系是否正确，集成代码知识库进行智能路径验证
        
        Args:
            file_path: 当前文件路径
            related_files: 相关文件字典
            
        Returns:
            验证结果，包含错误、警告和智能建议信息
        """
        result = {"valid": True, "errors": [], "warnings": [], "suggestions": []}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.html':
                # 验证HTML文件中的CSS和JS引用
                css_refs = re.findall(r'href=["\']([^"\']+\.css)["\']', content, re.IGNORECASE)
                js_refs = re.findall(r'src=["\']([^"\']+\.js)["\']', content, re.IGNORECASE)
                
                # 检查CSS引用路径
                for css_ref in css_refs:
                    # 智能路径验证：检查是否为相对路径且文件存在
                    if css_ref.startswith('/'):
                        result["errors"].append(f"HTML文件中的CSS引用使用绝对路径: {css_ref}，应该使用相对路径")
                        # 提供智能建议
                        suggested_path = self._get_suggested_path(file_path, css_ref, 'css')
                        if suggested_path:
                            result["suggestions"].append(f"建议将CSS引用路径改为: {suggested_path}")
                    elif css_ref.startswith('http'):
                        result["warnings"].append(f"HTML文件中的CSS引用使用外部URL: {css_ref}")
                    else:
                        # 检查引用的文件是否存在
                        css_filename = os.path.basename(css_ref)
                        if 'css' in related_files and css_filename not in os.path.basename(related_files['css']):
                            result["warnings"].append(f"HTML文件引用的CSS文件可能不匹配: {css_ref}")
                        
                        # 检查路径一致性（基于项目结构分析）
                        if not self._is_path_consistent_for_html(css_ref, related_files, 'css'):
                            result["warnings"].append(f"HTML文件中的CSS引用路径可能不一致: {css_ref}")
                            # 提供基于代码知识库的建议
                            suggested_path = self._get_suggested_path(file_path, css_ref, 'css')
                            if suggested_path:
                                result["suggestions"].append(f"建议CSS引用路径: {suggested_path}")
                
                # 检查JS引用路径
                for js_ref in js_refs:
                    if js_ref.startswith('/'):
                        result["errors"].append(f"HTML文件中的JS引用使用绝对路径: {js_ref}，应该使用相对路径")
                        # 提供智能建议
                        suggested_path = self._get_suggested_path(file_path, js_ref, 'js')
                        if suggested_path:
                            result["suggestions"].append(f"建议将JS引用路径改为: {suggested_path}")
                    elif js_ref.startswith('http'):
                        result["warnings"].append(f"HTML文件中的JS引用使用外部URL: {js_ref}")
                    else:
                        # 检查引用的文件是否存在
                        js_filename = os.path.basename(js_ref)
                        if 'js' in related_files and js_filename not in os.path.basename(related_files['js']):
                            result["warnings"].append(f"HTML文件引用的JS文件可能不匹配: {js_ref}")
                        
                        # 检查路径一致性
                        if not self._is_path_consistent_for_html(js_ref, related_files, 'js'):
                            result["warnings"].append(f"HTML文件中的JS引用路径可能不一致: {js_ref}")
                            # 提供基于代码知识库的建议
                            suggested_path = self._get_suggested_path(file_path, js_ref, 'js')
                            if suggested_path:
                                result["suggestions"].append(f"建议JS引用路径: {suggested_path}")
                
                # 检查导航链接
                nav_links = re.findall(r'href=["\']([^"\']+\.[^"\']+)["\']', content)
                for link in nav_links:
                    if link.startswith('/'):
                        result["errors"].append(f"HTML文件中的导航链接使用绝对路径: {link}，应该使用相对路径")
                        # 提供智能建议
                        suggested_path = self._get_suggested_path(file_path, link, 'html')
                        if suggested_path:
                            result["suggestions"].append(f"建议将导航链接路径改为: {suggested_path}")
                    elif link.startswith('http'):
                        result["warnings"].append(f"HTML文件中的导航链接使用外部URL: {link}")
            
            elif file_ext == '.js':
                # 验证JS文件中的数据引用和导航
                data_refs = re.findall(r'(?:fetch|import)\(["\']([^"\']+\.json)["\']', content, re.IGNORECASE)
                nav_refs = re.findall(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
                
                # 检查数据引用路径
                for data_ref in data_refs:
                    if data_ref.startswith('/'):
                        result["errors"].append(f"JS文件中的数据引用使用绝对路径: {data_ref}，应该使用相对路径")
                        # 提供智能建议
                        suggested_path = self._get_suggested_path(file_path, data_ref, 'json')
                        if suggested_path:
                            result["suggestions"].append(f"建议将数据引用路径改为: {suggested_path}")
                    elif data_ref.startswith('http'):
                        result["warnings"].append(f"JS文件中的数据引用使用外部URL: {data_ref}")
                    elif data_ref.startswith('/api/'):
                        result["errors"].append(f"JS文件中使用API路径: {data_ref}，应该使用本地数据文件路径")
                        # 提供智能建议
                        suggested_path = self._get_suggested_path(file_path, data_ref.replace('/api/', ''), 'json')
                        if suggested_path:
                            result["suggestions"].append(f"建议使用本地数据文件路径: {suggested_path}")
                    else:
                        # 检查引用的文件是否存在
                        data_filename = os.path.basename(data_ref)
                        if 'json' in related_files and data_filename not in os.path.basename(related_files['json']):
                            result["warnings"].append(f"JS文件引用的数据文件可能不匹配: {data_ref}")
                        
                        # 检查路径一致性
                        if not self._is_path_consistent_for_html(data_ref, related_files, 'data'):
                            result["warnings"].append(f"JS文件中的数据引用路径可能不一致: {data_ref}")
                            # 提供基于代码知识库的建议
                            suggested_path = self._get_suggested_path(file_path, data_ref, 'json')
                            if suggested_path:
                                result["suggestions"].append(f"建议数据引用路径: {suggested_path}")
                
                # 检查导航路径
                for nav_ref in nav_refs:
                    if nav_ref.startswith('/'):
                        result["errors"].append(f"JS文件中的导航路径使用绝对路径: {nav_ref}，应该使用相对路径")
                        # 提供智能建议
                        suggested_path = self._get_suggested_path(file_path, nav_ref, 'html')
                        if suggested_path:
                            result["suggestions"].append(f"建议将导航路径改为: {suggested_path}")
                    elif nav_ref.startswith('http'):
                        result["warnings"].append(f"JS文件中的导航路径使用外部URL: {nav_ref}")
                    elif 'paper/' in nav_ref and 'detail.html?id=' not in nav_ref:
                        result["warnings"].append(f"JS文件中的论文导航路径建议使用'detail.html?id='格式而不是'{nav_ref}'")
                        result["suggestions"].append("建议使用格式: 'detail.html?id={paper_id}'")
            
        except Exception as e:
            result["errors"].append(f"验证文件引用关系时出错: {str(e)}")
        
        result["valid"] = len(result["errors"]) == 0
        return result
    
    def _get_suggested_path(self, current_file: str, ref_path: str, target_type: str) -> str:
        """
        基于代码知识库获取建议的路径
        
        Args:
            current_file: 当前文件路径
            ref_path: 引用路径
            target_type: 目标文件类型（css/js/html/json）
            
        Returns:
            建议的路径，如果无法提供建议则返回空字符串
        """
        try:
            # 获取当前文件所在目录
            current_dir = os.path.dirname(current_file)
            
            # 使用代码知识库的路径建议功能
            suggested_paths = self.code_knowledge_base.suggest_web_file_paths(
                current_dir, 
                target_type
            )
            
            if suggested_paths:
                # 如果有建议路径，选择最合适的路径
                # 优先选择与当前文件同目录的路径
                for path in suggested_paths:
                    if path.startswith('./') or not path.startswith('../'):
                        return path
                
                # 如果没有同目录路径，返回第一个建议路径
                return suggested_paths[0]
            
            # 如果没有建议路径，基于常见的路径模式生成建议
            if target_type == 'css':
                # 对于CSS文件，建议使用相对路径
                return f"./styles.{target_type}"
            
            elif target_type == 'js':
                # 对于JS文件，建议使用相对路径
                return f"./script.{target_type}"
            
            elif target_type == 'html':
                # 对于HTML文件，建议使用相对路径
                return f"./index.{target_type}"
            
            elif target_type == 'json':
                # 对于JSON文件，建议使用相对路径
                return f"./data.{target_type}"
            
        except Exception as e:
            print(f"[Orchestrator] Warning: Failed to generate suggested path: {e}")
        
        # 如果无法提供智能建议，返回空字符串
        return ""
    
    def _is_path_consistent_for_html(self, ref_path: str, related_files: Dict[str, str], file_type: str) -> bool:
        """
        检查HTML文件中的引用路径是否与项目结构一致
        
        Args:
            ref_path: 引用路径
            related_files: 相关文件字典
            file_type: 文件类型（css/js/data）
            
        Returns:
            是否一致
        """
        # 如果没有相关文件信息，认为一致
        if file_type not in related_files:
            return True
            
        # 获取相关文件的路径
        related_file_path = related_files[file_type]
        related_dir = os.path.dirname(related_file_path)
        
        # 检查引用路径是否与相关文件路径一致
        ref_dir = os.path.dirname(ref_path)
        
        # 如果引用路径是相对路径且与相关文件路径不同，可能不一致
        if ref_dir and ref_dir != related_dir and not ref_dir.startswith('../'):
            return False
        
        # 使用代码知识库检查路径建议
        try:
            # 获取当前文件所在目录
            current_file_dir = os.path.dirname(related_file_path)
            
            # 使用代码知识库的路径建议功能
            suggested_paths = self.code_knowledge_base.suggest_web_file_paths(
                file_type, 
                current_file_dir
            )
            
            # 检查引用路径是否在建议路径中
            if suggested_paths and ref_path not in suggested_paths:
                # 如果引用路径不在建议路径中，但路径格式正确，仍然认为一致
                # 这里可以添加更智能的路径匹配逻辑
                return True  # 暂时保持宽松策略
                
        except Exception as e:
            # 如果代码知识库功能不可用，回退到原有逻辑
            print(f"[Orchestrator] Warning: Failed to use code knowledge base for path validation: {e}")
            
        return True

    def _print_execution_summary(self):
        """打印执行摘要"""
        print("\n" + "="*50)
        print("EXECUTION SUMMARY")
        print("="*50)
        
        completed = len([t for t in self.memory['task_history'] if t['status'] == TaskStatus.COMPLETED.value])
        failed = len([t for t in self.memory['task_history'] if t['status'] == TaskStatus.FAILED.value])
        total = len(self.memory['task_history'])
        
        print(f"Total tasks: {total}")
        print(f"Completed: {completed}")
        print(f"Failed: {failed}")
        print(f"Success rate: {completed/total*100:.1f}%" if total > 0 else "Success rate: N/A")
        
        if self.memory['error_logs']:
            print(f"\nErrors encountered: {len(self.memory['error_logs'])}")
            for error in self.memory['error_logs'][:3]:  # 显示前3个错误
                print(f"  - {error['task_id']}: {error['error']}")
        
        print("="*50)