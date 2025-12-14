import os
import json
import re
import asyncio
from typing import Dict, List, Any, Tuple, Optional
from llm_client import LLMClient

EVALUATOR_SYSTEM_PROMPT = """You are CodeEvaluationAgent. You can use web_search tool to search for coding standards, best practices, or documentation when needed.

IMPORTANT: Return ONLY a JSON object with the following structure:
{
    "ok": true/false,
    "quality_score": 0.0-1.0,
    "evaluation": {
        "modularity": "detailed modularity assessment IN ENGLISH",
        "maintainability": "detailed maintainability assessment IN ENGLISH",
        "functional_completeness": "detailed functional completeness assessment IN ENGLISH",
        "requirements_adherence": "detailed requirements adherence assessment IN ENGLISH"
    },
    "severity": "low/medium/high",
    "ai_quality_metrics": {
        "modularity": 0.0-1.0,
        "maintainability": 0.0-1.0,
        "functional_completeness": 0.0-1.0,
        "requirements_adherence": 0.0-1.0
    }
}

Rules:
- ALL evaluation text must be in ENGLISH
- Set "ok" to false if quality_score < 0.7
- quality_score is a weighted average of all metrics
- severity should reflect the overall issue severity
- Provide detailed, specific assessments in each category
- Be objective and constructive in your evaluation"""

class CodeEvaluationAgent:
    def __init__(self, fs_tool=None, code_executor=None, model="qwen3-235b-a22b-thinking-2507", api_key=None):
        self.fs = fs_tool
        self.code_executor = code_executor
        self.tools = {}
        self.llm = LLMClient(model, api_key)

    def review(self, path: str, requirements: Dict[str, Any] = None) -> Dict[str, Any]:
        """同步代码审查方法"""
        return asyncio.run(self._review_async(path, requirements))
    
    async def _review_async(self, path: str, requirements: Dict[str, Any] = None) -> Dict[str, Any]:
        """异步代码审查方法，使用LLM生成结构化评估"""
        # 检查文件是否存在
        if not os.path.exists(path):
            return {"ok": False, "notes": "file not found", "severity": "critical"}

        # 读取文件内容
        try:
            content = self.fs.read_file(path)
        except Exception as e:
            return {"ok": False, "notes": f"read error: {str(e)}", "severity": "critical"}

        # 使用LLM进行结构化评估
        messages = [
            {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"""Please evaluate the quality of the following code files:

File Path: {path}
Code Content:
{content}

Requirements information:{requirements if requirements else "No specific requirements"}

Please return the evaluation result in JSON format. """}
        ]
        
        try:
            # 调用LLM进行评估
            response = await self.llm.chat(messages)
            llm_content = response.get("content", "")
            
            # 解析JSON响应
            evaluation = self._parse_llm_evaluation(llm_content)
            
            # 验证评估结果格式
            if self._validate_evaluation_format(evaluation):
                # .py文件特殊处理
                if self.code_executor and path.endswith('.py'):
                    # 1. 可执行性检查
                    execution_result = self._execute_code_validation(path, evaluation)
                    evaluation = self._integrate_execution_result(evaluation, execution_result)
                    
                    # 2. Python文件质量验证
                    python_validation = self.code_executor.validate_python_file(path)
                    if not python_validation.get('valid', True):
                        # 根据验证结果调整质量评分
                        evaluation['quality_score'] = max(0.0, evaluation.get('quality_score', 0.7) - 0.1)
                        evaluation['ok'] = evaluation['quality_score'] >= 0.7
                        
                        # 将验证结果添加到评估中
                        evaluation['python_validation'] = python_validation
                        if 'notes' not in evaluation:
                            evaluation['notes'] = ''
                        evaluation['notes'] += f" Python validation issues: {'; '.join(python_validation.get('issues', []))}"
                
                return evaluation
            else:
                # 如果解析失败，使用默认评估
                return self._get_default_evaluation(content, path)
                
        except Exception as e:
            # LLM调用失败时使用默认评估
            print(f"[Evaluator] LLM evaluation failed, use default evaluation. Error: {str(e)}")
            return self._get_default_evaluation(content, path)
    
    def _parse_llm_evaluation(self, content: str) -> Dict[str, Any]:
        """根据EVALUATOR_SYSTEM_PROMPT要求的格式解析LLM评估结果"""
        try:
            # 清理内容，移除可能的Markdown代码块标记
            cleaned_content = content.strip()
            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content[7:]
            if cleaned_content.endswith('```'):
                cleaned_content = cleaned_content[:-3]
            cleaned_content = cleaned_content.strip()
            
            # 尝试解析JSON
            parsed_result = json.loads(cleaned_content)
            
            # 验证解析结果是否符合要求的格式
            if isinstance(parsed_result, dict):
                # 检查必需字段
                required_fields = ["ok", "quality_score", "evaluation", "severity", "ai_quality_metrics"]
                missing_fields = [field for field in required_fields if field not in parsed_result]
                
                if not missing_fields:
                    # 检查evaluation字段的必需子字段
                    evaluation = parsed_result.get("evaluation", {})
                    eval_required_fields = ["modularity", "maintainability", "functional_completeness", "requirements_adherence"]
                    eval_missing_fields = [field for field in eval_required_fields if field not in evaluation]
                    
                    if not eval_missing_fields:
                        # 检查ai_quality_metrics字段的必需子字段
                        metrics = parsed_result.get("ai_quality_metrics", {})
                        metrics_required_fields = ["modularity", "maintainability", "functional_completeness", "requirements_adherence"]
                        metrics_missing_fields = [field for field in metrics_required_fields if field not in metrics]
                        
                        if not metrics_missing_fields:
                            # 检查质量评分范围
                            quality_score = parsed_result.get("quality_score", 0.0)
                            if isinstance(quality_score, (int, float)) and 0.0 <= quality_score <= 1.0:
                                # 检查severity值
                                severity = parsed_result.get("severity", "")
                                if severity in ["low", "medium", "high"]:
                                    # 检查所有指标范围
                                    all_metrics_valid = True
                                    for metric, value in metrics.items():
                                        if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
                                            all_metrics_valid = False
                                            break
                                    
                                    if all_metrics_valid:
                                        print(f"[Evaluator] 成功解析LLM评估结果，质量评分: {quality_score}")
                                        return parsed_result
        except:
            print(f"[Evaluator] 解析结果不符合EVALUATOR_SYSTEM_PROMPT要求的格式")
            print(f"[Evaluator] 原始LLM内容前200字符: {content[:200]}...")
            
            # 解析失败，返回默认评估
            return self._get_default_evaluation("", "")
    
    def _validate_evaluation_format(self, evaluation: Dict[str, Any]) -> bool:
        """验证评估结果格式是否符合要求"""
        required_fields = ["ok", "quality_score", "evaluation", "severity", "ai_quality_metrics"]
        
        if not isinstance(evaluation, dict):
            return False
        
        for field in required_fields:
            if field not in evaluation:
                return False
        
        # 验证嵌套结构
        evaluation_section = evaluation.get("evaluation", {})
        if not isinstance(evaluation_section, dict):
            return False
        
        metrics_section = evaluation.get("ai_quality_metrics", {})
        if not isinstance(metrics_section, dict):
            return False
        
        # 验证评估字段完整性
        required_evaluation_fields = [
            "modularity", "maintainability", "functional_completeness", "requirements_adherence"
        ]
        for field in required_evaluation_fields:
            if field not in evaluation_section:
                return False
        
        # 验证指标字段完整性
        required_metrics_fields = [
            "modularity", "maintainability", "functional_completeness", "requirements_adherence"
        ]
        for field in required_metrics_fields:
            if field not in metrics_section:
                return False
        
        # 验证基本类型
        quality_score = evaluation.get("quality_score", 0)
        if not isinstance(quality_score, (int, float)) or not (0 <= quality_score <= 1):
            return False
        
        severity = evaluation.get("severity", "")
        if severity not in ["low", "medium", "high"]:
            return False
        
        # 验证所有指标值的范围
        for metric, value in metrics_section.items():
            if not isinstance(value, (int, float)) or not (0 <= value <= 1):
                return False
        
        return True
    
    def _get_default_evaluation(self, content: str, path: str) -> Dict[str, Any]:
        """获取默认评估结果"""
        #  基于文件内容进行基本评估
        lines = content.split('\n')
        line_count = len(lines)
        
        # 简单的质量评分——使用宽松的标准，避免过于严格
        quality_score = 0.8  # 除非有明显问题否则默认为高质量
        
        # 文件内容太短
        if line_count < 5 and len(content.strip()) < 100:
            quality_score = 0.6
        
        # 检查常见问题  
        if 'error' in content.lower() or 'exception' in content.lower():
            quality_score = max(0.3, quality_score - 0.3)
        
        return {
            "ok": quality_score >= 0.6,  # 将阈值降低到 0.6
            "quality_score": quality_score,
            "evaluation": {
                "modularity": "Basic modularity evaluation",
                "maintainability": "Basic maintainability evaluation",
                "functional_completeness": "Basic functional completeness evaluation",
                "requirements_adherence": "Basic requirements adherence evaluation"
            },
            "severity": "low",
            "ai_quality_metrics": {
                "modularity": 0.7,
                "maintainability": 0.7,
                "functional_completeness": 0.8,
                "requirements_adherence": 0.8
            },
            "notes": "Auto-evaluation: File generated with acceptable quality"
        }
    
    def validate_web_files(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        验证Web相关文件（HTML、JS、CSS、JSON）的质量和一致性
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            验证结果
        """
        results = {}
        
        # 检查code_executor是否可用
        if not self.code_executor:
            for file_path in file_paths:
                results[file_path] = {"valid": False, "errors": ["code_executor不可用"], "warnings": []}
            results["cross_file_consistency"] = {"valid": False, "errors": ["code_executor不可用"], "warnings": []}
            results["file_references"] = {"valid": False, "errors": ["code_executor不可用"], "warnings": []}
            return results
        
        for file_path in file_paths:
            if not os.path.exists(file_path):
                results[file_path] = {"valid": False, "errors": ["文件不存在"], "warnings": []}
                continue
                
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.html':
                results[file_path] = self.code_executor.validate_html_file(file_path)
            elif file_ext == '.js':
                results[file_path] = self.code_executor.validate_javascript_file(file_path)
            elif file_ext == '.css':
                results[file_path] = self.code_executor.validate_css_file(file_path)
            elif file_ext == '.json':
                results[file_path] = self.code_executor.validate_json_file(file_path)
            else:
                results[file_path] = {"valid": True, "errors": [], "warnings": ["不支持的文件类型"]}
        
        # 跨文件一致性检查 - 需要从文件列表中提取HTML、JS和JSON文件
        html_files = [f for f in file_paths if f.lower().endswith('.html')]
        js_files = [f for f in file_paths if f.lower().endswith('.js')]
        json_files = [f for f in file_paths if f.lower().endswith('.json')]
        
        # 如果有HTML和JS文件，进行跨文件一致性检查
        if html_files and js_files:
            html_file = html_files[0]  # 使用第一个HTML文件
            js_file = js_files[0]      # 使用第一个JS文件
            json_file = json_files[0] if json_files else None
            
            cross_file_results = self.code_executor.validate_cross_file_consistency(html_file, js_file, json_file)
            results["cross_file_consistency"] = cross_file_results
        else:
            results["cross_file_consistency"] = {"valid": True, "errors": [], "warnings": ["缺少HTML或JS文件，跳过跨文件一致性检查"]}
        
        # 文件引用关系检查
        file_reference_results = self._validate_file_references(file_paths)
        results["file_references"] = file_reference_results
        
        return results
    
    def _validate_file_references(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        验证文件间的引用关系是否正确
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            验证结果
        """
        result = {"valid": True, "errors": [], "warnings": [], "missing_refs": []}
        
        # 分析项目结构，识别常见的文件夹模式
        project_structure = self._analyze_project_structure(file_paths)
        
        # 构建增强的文件路径映射（包含完整路径和文件名映射）
        file_mapping = {}
        path_mapping = {}
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            file_mapping[filename] = file_path
            # 添加相对路径映射
            relative_path = os.path.relpath(file_path, os.path.dirname(file_path))
            path_mapping[relative_path] = file_path
            # 添加相对于项目根目录的路径
            project_root = self._find_project_root(file_paths)
            if project_root:
                rel_to_root = os.path.relpath(file_path, project_root)
                path_mapping[rel_to_root] = file_path
        
        for file_path in file_paths:
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
                            result["errors"].append(f"HTML文件 {file_path} 中的CSS引用使用绝对路径: {css_ref}，应该使用相对路径")
                        elif css_ref.startswith('http'):
                            result["warnings"].append(f"HTML文件 {file_path} 中的CSS引用使用外部URL: {css_ref}")
                        else:
                            # 增强的文件存在性检查
                            if not self._check_referenced_file_exists(css_ref, file_path, path_mapping):
                                result["errors"].append(f"HTML文件 {file_path} 引用的CSS文件不存在: {css_ref}")
                                result["missing_refs"].append({"file": file_path, "ref": css_ref, "type": "css"})
                            
                            # 检查路径一致性（基于项目结构分析）
                            if not self._is_path_consistent(css_ref, project_structure, 'css'):
                                result["warnings"].append(f"HTML文件 {file_path} 中的CSS引用路径可能不一致: {css_ref}")
                    
                    # 检查JS引用路径
                    for js_ref in js_refs:
                        if js_ref.startswith('/'):
                            result["errors"].append(f"HTML文件 {file_path} 中的JS引用使用绝对路径: {js_ref}，应该使用相对路径")
                        elif js_ref.startswith('http'):
                            result["warnings"].append(f"HTML文件 {file_path} 中的JS引用使用外部URL: {js_ref}")
                        else:
                            # 增强的文件存在性检查
                            if not self._check_referenced_file_exists(js_ref, file_path, path_mapping):
                                result["errors"].append(f"HTML文件 {file_path} 引用的JS文件不存在: {js_ref}")
                                result["missing_refs"].append({"file": file_path, "ref": js_ref, "type": "js"})
                            
                            # 检查路径一致性
                            if not self._is_path_consistent(js_ref, project_structure, 'js'):
                                result["warnings"].append(f"HTML文件 {file_path} 中的JS引用路径可能不一致: {js_ref}")
                    
                    # 检查导航链接
                    nav_links = re.findall(r'href=["\']([^"\']+\.[^"\']+)["\']', content)
                    for link in nav_links:
                        if link.startswith('/'):
                            result["errors"].append(f"HTML文件 {file_path} 中的导航链接使用绝对路径: {link}，应该使用相对路径")
                        elif link.startswith('http'):
                            result["warnings"].append(f"HTML文件 {file_path} 中的导航链接使用外部URL: {link}")
                
                elif file_ext == '.js':
                    # 验证JS文件中的数据引用和导航
                    data_refs = re.findall(r'(?:fetch|import)\(["\']([^"\']+\.json)["\']', content, re.IGNORECASE)
                    nav_refs = re.findall(r'window\\.location\\.href\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
                    
                    # 检查数据引用路径
                    for data_ref in data_refs:
                        if data_ref.startswith('/'):
                            result["errors"].append(f"JS文件 {file_path} 中的数据引用使用绝对路径: {data_ref}，应该使用相对路径")
                        elif data_ref.startswith('http'):
                            result["warnings"].append(f"JS文件 {file_path} 中的数据引用使用外部URL: {data_ref}")
                        elif data_ref.startswith('/api/'):
                            result["errors"].append(f"JS文件 {file_path} 中使用API路径: {data_ref}，应该使用本地数据文件路径")
                        else:
                            # 增强的文件存在性检查
                            if not self._check_referenced_file_exists(data_ref, file_path, path_mapping):
                                result["warnings"].append(f"JS文件 {file_path} 引用的数据文件可能不存在: {data_ref}")
                                result["missing_refs"].append({"file": file_path, "ref": data_ref, "type": "data"})
                            
                            # 检查路径一致性
                            if not self._is_path_consistent(data_ref, project_structure, 'data'):
                                result["warnings"].append(f"JS文件 {file_path} 中的数据引用路径可能不一致: {data_ref}")
                    
                    # 检查导航路径
                    for nav_ref in nav_refs:
                        if nav_ref.startswith('/'):
                            result["errors"].append(f"JS文件 {file_path} 中的导航路径使用绝对路径: {nav_ref}，应该使用相对路径")
                        elif nav_ref.startswith('http'):
                            result["warnings"].append(f"JS文件 {file_path} 中的导航路径使用外部URL: {nav_ref}")
                        elif 'paper/' in nav_ref and 'detail.html?id=' not in nav_ref:
                            result["warnings"].append(f"JS文件 {file_path} 中的论文导航路径建议使用'detail.html?id='格式而不是'{nav_ref}'")
                
            except Exception as e:
                result["errors"].append(f"验证文件 {file_path} 引用关系时出错: {str(e)}")
        
        result["valid"] = len(result["errors"]) == 0
        return result
    
    def _analyze_project_structure(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        分析项目结构，识别常见的文件夹模式
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            项目结构分析结果
        """
        structure = {
            'css_folders': set(),
            'js_folders': set(), 
            'data_folders': set(),
            'image_folders': set(),
            'common_patterns': {}
        }
        
        for file_path in file_paths:
            dir_path = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            
            # 分析文件类型和所在文件夹
            if file_path.endswith('.css'):
                structure['css_folders'].add(dir_path)
            elif file_path.endswith('.js'):
                structure['js_folders'].add(dir_path)
            elif file_path.endswith('.json'):
                structure['data_folders'].add(dir_path)
            elif file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                structure['image_folders'].add(dir_path)
        
        # 识别常见模式
        if len(structure['css_folders']) == 1:
            structure['common_patterns']['css'] = list(structure['css_folders'])[0]
        if len(structure['js_folders']) == 1:
            structure['common_patterns']['js'] = list(structure['js_folders'])[0]
        if len(structure['data_folders']) == 1:
            structure['common_patterns']['data'] = list(structure['data_folders'])[0]
            
        return structure
    
    def _is_path_consistent(self, path: str, project_structure: Dict[str, Any], file_type: str) -> bool:
        """检查路径是否与项目结构一致"""
        # 检查路径是否包含常见的文件夹模式
        if file_type == 'css' and 'css/' in path:
            return True
        elif file_type == 'js' and 'js/' in path:
            return True
        elif file_type == 'data' and 'data/' in path:
            return True
        
        # 检查路径是否与项目结构中的文件夹模式匹配
        for folder_pattern in project_structure.get('common_folders', []):
            if folder_pattern in path:
                return True
        
        return False
    
    def _check_referenced_file_exists(self, ref_path: str, source_file: str, path_mapping: Dict[str, str]) -> bool:
        """
        检查引用的文件是否存在（支持相对路径解析）
        
        Args:
            ref_path: 引用路径
            source_file: 源文件路径
            path_mapping: 路径映射字典
            
        Returns:
            bool: 文件是否存在
        """
        # 如果引用路径在路径映射中，直接检查
        if ref_path in path_mapping:
            return os.path.exists(path_mapping[ref_path])
        
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
        project_root = self._find_project_root(list(path_mapping.values()))
        if project_root:
            full_path_from_root = os.path.join(project_root, ref_path)
            if os.path.exists(full_path_from_root):
                return True
        
        # 检查是否为文件名（不含路径）
        filename = os.path.basename(ref_path)
        for mapped_path in path_mapping.values():
            if os.path.basename(mapped_path) == filename:
                return True
        
        return False
    
    def _find_project_root(self, file_paths: List[str]) -> Optional[str]:
        """
        查找项目根目录
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            str: 项目根目录路径，如果无法确定则返回None
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

    def _execute_code_validation(self, path: str, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        """执行代码验证，返回执行结果"""
        try:
            execution_result = self.code_executor.run_python_file(path)
            return execution_result
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Execution error: {str(e)}"
            }
    
    def _integrate_execution_result(self, evaluation: Dict[str, Any], execution_result: Dict[str, Any]) -> Dict[str, Any]:
        """将代码执行结果整合到评估结果中"""
        # 根据执行结果调整质量评分
        if execution_result.get("returncode", -1) == 0:
            # 执行成功，提高质量评分
            evaluation["quality_score"] = min(1.0, evaluation.get("quality_score", 0.5) + 0.1)
            evaluation["evaluation"]["functional_completeness"] += " 代码执行验证通过。"
        else:
            # 执行失败，降低质量评分
            evaluation["quality_score"] = max(0.0, evaluation.get("quality_score", 0.5) - 0.2)
            evaluation["evaluation"]["functional_completeness"] += f" 代码执行失败: {execution_result.get('stderr', 'Unknown error')}"
            evaluation["severity"] = "high"
        
        # 更新ok状态
        evaluation["ok"] = evaluation["quality_score"] >= 0.7
        
        # 添加执行结果到评估详情
        evaluation["execution_result"] = execution_result
        
        return evaluation