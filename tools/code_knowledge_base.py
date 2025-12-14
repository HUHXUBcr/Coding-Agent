"""
代码知识库模块 - 用于管理跨文件代码重用和依赖分析

功能：
1. 解析Python代码，提取函数、类、模块定义
2. 解析Web文件（HTML/CSS/JS），提取文件结构和引用关系
3. 维护代码知识库，记录所有已生成代码的结构信息
4. 提供智能导入建议、代码重用和路径引用功能
"""

import ast
import os
import re
from typing import Dict, List, Any, Set, Optional
from dataclasses import dataclass


@dataclass
class FunctionInfo:
    """函数信息"""
    name: str
    parameters: List[str]
    return_type: Optional[str]
    is_async: bool
    file_path: str
    line_number: int
    docstring: Optional[str] = None


@dataclass
class ClassInfo:
    """类信息"""
    name: str
    methods: List[FunctionInfo]
    base_classes: List[str]
    file_path: str
    line_number: int
    docstring: Optional[str] = None


@dataclass
class WebFileInfo:
    """Web文件信息"""
    file_path: str
    file_type: str  # html, css, js
    references: List[str]  # 引用的其他文件
    elements: List[str]  # HTML元素/CSS选择器/JS函数
    dependencies: List[str]  # 依赖的文件


@dataclass
class ModuleInfo:
    """模块信息"""
    name: str
    file_path: str
    functions: List[FunctionInfo]
    classes: List[ClassInfo]
    imports: List[str]


@dataclass
class ProjectStructure:
    """项目结构信息"""
    web_files: Dict[str, WebFileInfo]  # 文件路径 -> Web文件信息
    file_hierarchy: Dict[str, List[str]]  # 目录 -> 文件列表
    path_patterns: Dict[str, List[str]]  # 文件类型 -> 常见路径模式


class CodeKnowledgeBase:
    """代码知识库 - 管理跨文件代码重用和项目结构"""
    
    def __init__(self):
        self.modules: Dict[str, ModuleInfo] = {}
        self.function_index: Dict[str, FunctionInfo] = {}
        self.class_index: Dict[str, ClassInfo] = {}
        self.import_dependencies: Dict[str, Set[str]] = {}
        
        # Web文件支持
        self.web_files: Dict[str, WebFileInfo] = {}
        self.project_structure: ProjectStructure = ProjectStructure(
            web_files={},
            file_hierarchy={},
            path_patterns={
                'css': ['css/', 'styles/', 'assets/css/'],
                'js': ['js/', 'scripts/', 'assets/js/'],
                'images': ['images/', 'assets/images/', 'img/'],
                'data': ['data/', 'assets/data/']
            }
        )
        
    def add_module(self, file_path: str, content: str) -> ModuleInfo:
        """
        解析Python文件并添加到知识库
        
        Args:
            file_path: 文件路径
            content: 文件内容
            
        Returns:
            ModuleInfo: 解析后的模块信息
        """
        module_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # 解析代码结构
        functions = self._extract_functions(content, file_path)
        classes = self._extract_classes(content, file_path)
        imports = self._extract_imports(content)
        
        module_info = ModuleInfo(
            name=module_name,
            file_path=file_path,
            functions=functions,
            classes=classes,
            imports=imports
        )
        
        # 添加到知识库
        self.modules[module_name] = module_info
        
        # 更新索引
        for func in functions:
            func_key = f"{module_name}.{func.name}"
            self.function_index[func_key] = func
            
        for cls in classes:
            cls_key = f"{module_name}.{cls.name}"
            self.class_index[cls_key] = cls
            
            # 添加类方法到函数索引
            for method in cls.methods:
                method_key = f"{module_name}.{cls.name}.{method.name}"
                self.function_index[method_key] = method
        
        return module_info
    
    def add_web_file(self, file_path: str, content: str) -> WebFileInfo:
        """
        解析Web文件并添加到知识库
        
        Args:
            file_path: 文件路径
            content: 文件内容
            
        Returns:
            WebFileInfo: 解析后的Web文件信息
        """
        file_ext = os.path.splitext(file_path)[1].lower()
        file_type = file_ext[1:] if file_ext else 'unknown'
        
        # 解析不同类型的Web文件
        if file_type == 'html':
            web_info = self._parse_html_file(file_path, content)
        elif file_type == 'css':
            web_info = self._parse_css_file(file_path, content)
        elif file_type == 'js':
            web_info = self._parse_js_file(file_path, content)
        else:
            # 对于其他类型的文件，创建基本信息
            web_info = WebFileInfo(
                file_path=file_path,
                file_type=file_type,
                references=[],
                elements=[],
                dependencies=[]
            )
        
        # 添加到知识库
        self.web_files[file_path] = web_info
        
        # 更新项目结构
        self._update_project_structure(file_path, file_type)
        
        return web_info
    
    def _parse_html_file(self, file_path: str, content: str) -> WebFileInfo:
        """解析HTML文件"""
        references = []
        elements = []
        
        # 提取CSS引用
        css_refs = re.findall(r'href=["\']([^"\']+\.css)["\']', content, re.IGNORECASE)
        references.extend(css_refs)
        
        # 提取JS引用
        js_refs = re.findall(r'src=["\']([^"\']+\.js)["\']', content, re.IGNORECASE)
        references.extend(js_refs)
        
        # 提取图片引用
        img_refs = re.findall(r'src=["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg))["\']', content, re.IGNORECASE)
        references.extend(img_refs)
        
        # 提取HTML元素
        element_patterns = [
            r'<([a-zA-Z][a-zA-Z0-9]*)\b',  # 标签名
            r'id=["\']([^"\']+)["\']',    # ID属性
            r'class=["\']([^"\']+)["\']'  # class属性
        ]
        
        for pattern in element_patterns:
            matches = re.findall(pattern, content)
            elements.extend(matches)
        
        return WebFileInfo(
            file_path=file_path,
            file_type='html',
            references=references,
            elements=elements,
            dependencies=css_refs + js_refs
        )
    
    def _parse_css_file(self, file_path: str, content: str) -> WebFileInfo:
        """解析CSS文件"""
        references = []
        elements = []
        
        # 提取CSS选择器
        selectors = re.findall(r'([^{}]+)\s*\{', content)
        for selector in selectors:
            selector = selector.strip()
            if selector and selector not in ['@media', '@keyframes', '@import']:
                elements.append(selector)
        
        # 提取@import引用
        import_refs = re.findall(r'@import\s+["\']([^"\']+)["\']', content, re.IGNORECASE)
        references.extend(import_refs)
        
        # 提取url引用
        url_refs = re.findall(r'url\(["\']?([^"\')]+)["\']?\)', content, re.IGNORECASE)
        references.extend(url_refs)
        
        return WebFileInfo(
            file_path=file_path,
            file_type='css',
            references=references,
            elements=elements,
            dependencies=import_refs
        )
    
    def _parse_js_file(self, file_path: str, content: str) -> WebFileInfo:
        """解析JS文件"""
        references = []
        elements = []
        
        # 提取函数定义
        function_pattern = r'(?:function\s+([a-zA-Z_$][\w$]*)|const\s+([a-zA-Z_$][\w$]*)\s*=|let\s+([a-zA-Z_$][\w$]*)\s*=|var\s+([a-zA-Z_$][\w$]*)\s*=)\s*(?:async\s*)?function'
        function_matches = re.findall(function_pattern, content)
        for match in function_matches:
            for name in match:
                if name:
                    elements.append(f"function:{name}")
                    break
        
        # 提取类定义
        class_pattern = r'class\s+([a-zA-Z_$][\w$]*)'
        class_matches = re.findall(class_pattern, content)
        elements.extend([f"class:{name}" for name in class_matches])
        
        # 提取import/require引用
        import_refs = re.findall(r'(?:import|require)\(["\']([^"\']+)["\']\)', content, re.IGNORECASE)
        references.extend(import_refs)
        
        # 提取fetch/ajax请求
        fetch_refs = re.findall(r'(?:fetch|ajax|axios\.get|axios\.post)\(["\']([^"\']+)["\']', content, re.IGNORECASE)
        references.extend(fetch_refs)
        
        return WebFileInfo(
            file_path=file_path,
            file_type='js',
            references=references,
            elements=elements,
            dependencies=import_refs
        )
    
    def _update_project_structure(self, file_path: str, file_type: str):
        """更新项目结构信息"""
        # 获取文件所在目录
        dir_path = os.path.dirname(file_path)
        
        # 更新文件层次结构
        if dir_path not in self.project_structure.file_hierarchy:
            self.project_structure.file_hierarchy[dir_path] = []
        
        if file_path not in self.project_structure.file_hierarchy[dir_path]:
            self.project_structure.file_hierarchy[dir_path].append(file_path)
        
        # 更新Web文件信息
        self.project_structure.web_files[file_path] = self.web_files[file_path]
    
    def analyze_project_structure(self, base_dir: str) -> ProjectStructure:
        """
        分析项目结构
        
        Args:
            base_dir: 项目根目录
            
        Returns:
            ProjectStructure: 项目结构信息
        """
        # 扫描项目目录
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                file_path = os.path.join(root, file)
                
                # 跳过隐藏文件和特定目录
                if file.startswith('.') or '__pycache__' in root:
                    continue
                
                # 读取文件内容并解析
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    file_ext = os.path.splitext(file)[1].lower()
                    
                    # 根据文件类型调用相应的解析方法
                    if file_ext == '.py':
                        self.add_module(file_path, content)
                    elif file_ext in ['.html', '.css', '.js']:
                        self.add_web_file(file_path, content)
                        
                except (UnicodeDecodeError, PermissionError, FileNotFoundError):
                    # 跳过无法读取的文件
                    continue
        
        return self.project_structure
    
    def _extract_functions(self, content: str, file_path: str) -> List[FunctionInfo]:
        """提取函数定义"""
        functions = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # 提取函数信息
                    func_name = node.name
                    
                    # 提取参数
                    parameters = []
                    for arg in node.args.args:
                        parameters.append(arg.arg)
                    
                    # 处理*args和**kwargs
                    if node.args.vararg:
                        parameters.append(f"*{node.args.vararg.arg}")
                    if node.args.kwarg:
                        parameters.append(f"**{node.args.kwarg.arg}")
                    
                    # 提取返回类型注解
                    return_type = None
                    if node.returns:
                        if isinstance(node.returns, ast.Name):
                            return_type = node.returns.id
                        elif isinstance(node.returns, ast.Subscript):
                            return_type = ast.unparse(node.returns)
                    
                    # 检查是否是异步函数
                    is_async = isinstance(node, ast.AsyncFunctionDef)
                    
                    # 提取文档字符串
                    docstring = ast.get_docstring(node)
                    
                    function_info = FunctionInfo(
                        name=func_name,
                        parameters=parameters,
                        return_type=return_type,
                        is_async=is_async,
                        file_path=file_path,
                        line_number=node.lineno,
                        docstring=docstring
                    )
                    
                    functions.append(function_info)
                    
        except SyntaxError:
            # 如果AST解析失败，使用正则表达式作为备选方案
            functions = self._extract_functions_regex(content, file_path)
        
        return functions
    
    def _extract_functions_regex(self, content: str, file_path: str) -> List[FunctionInfo]:
        """使用正则表达式提取函数定义（AST解析失败时的备选方案）"""
        functions = []
        
        # 支持: def func(...) -> type: 和 async def func(...):
        func_pattern = r'(async\s+)?def\s+([a-zA-Z_]\w*)\s*\(([^)]*)\)\s*(->\s*[^:]+)?:'
        matches = re.finditer(func_pattern, content, re.MULTILINE)
        
        for match in matches:
            is_async = bool(match.group(1))
            func_name = match.group(2)
            params_str = match.group(3)
            return_type = match.group(4).strip() if match.group(4) else None
            
            # 分析参数
            parameters = []
            if params_str.strip():
                param_list = params_str.split(',')
                for param in param_list:
                    param = param.strip()
                    if param:
                        parameters.append(param)
            
            # 计算行号
            line_number = content[:match.start()].count('\n') + 1
            
            function_info = FunctionInfo(
                name=func_name,
                parameters=parameters,
                return_type=return_type,
                is_async=is_async,
                file_path=file_path,
                line_number=line_number
            )
            
            functions.append(function_info)
        
        return functions
    
    def _extract_classes(self, content: str, file_path: str) -> List[ClassInfo]:
        """提取类定义"""
        classes = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # 提取类信息
                    class_name = node.name
                    
                    # 提取基类
                    base_classes = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            base_classes.append(base.id)
                    
                    # 提取类方法
                    methods = []
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            # 提取方法信息（简化版）
                            method_name = child.name
                            
                            # 提取参数
                            method_params = []
                            for arg in child.args.args:
                                method_params.append(arg.arg)
                            
                            # 提取返回类型
                            method_return_type = None
                            if child.returns:
                                if isinstance(child.returns, ast.Name):
                                    method_return_type = child.returns.id
                            
                            is_async = isinstance(child, ast.AsyncFunctionDef)
                            
                            method_info = FunctionInfo(
                                name=method_name,
                                parameters=method_params,
                                return_type=method_return_type,
                                is_async=is_async,
                                file_path=file_path,
                                line_number=child.lineno
                            )
                            
                            methods.append(method_info)
                    
                    # 提取文档字符串
                    docstring = ast.get_docstring(node)
                    
                    class_info = ClassInfo(
                        name=class_name,
                        methods=methods,
                        base_classes=base_classes,
                        file_path=file_path,
                        line_number=node.lineno,
                        docstring=docstring
                    )
                    
                    classes.append(class_info)
                    
        except SyntaxError:
            # 如果AST解析失败，使用正则表达式作为备选方案
            classes = self._extract_classes_regex(content, file_path)
        
        return classes
    
    def _extract_classes_regex(self, content: str, file_path: str) -> List[ClassInfo]:
        """使用正则表达式提取类定义（AST解析失败时的备选方案）"""
        classes = []
        
        # 匹配类定义: class ClassName(BaseClass):
        class_pattern = r'class\s+([a-zA-Z_]\w*)\s*(?:\(([^)]*)\))?:'
        matches = re.finditer(class_pattern, content, re.MULTILINE)
        
        for match in matches:
            class_name = match.group(1)
            base_classes_str = match.group(2) if match.group(2) else ""
            
            # 解析基类
            base_classes = []
            if base_classes_str:
                base_classes = [bc.strip() for bc in base_classes_str.split(',')]
            
            # 计算行号
            line_number = content[:match.start()].count('\n') + 1
            
            # 简化版：不提取类方法（正则表达式较复杂）
            class_info = ClassInfo(
                name=class_name,
                methods=[],
                base_classes=base_classes,
                file_path=file_path,
                line_number=line_number
            )
            
            classes.append(class_info)
        
        return classes
    
    def _extract_imports(self, content: str) -> List[str]:
        """提取导入语句"""
        imports = []
        
        # 匹配import语句
        import_patterns = [
            r'^import\s+([^\n]+)',  # import module
            r'^from\s+([^\s]+)\s+import',  # from module import
        ]
        
        for pattern in import_patterns:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                import_stmt = match.group(1).strip()
                if import_stmt and not import_stmt.startswith('.'):  # 排除相对导入
                    imports.append(import_stmt)
        
        return imports
    
    def find_function(self, function_name: str) -> Optional[FunctionInfo]:
        """查找函数定义"""
        return self.function_index.get(function_name)
    
    def find_class(self, class_name: str) -> Optional[ClassInfo]:
        """查找类定义"""
        return self.class_index.get(class_name)
    
    def get_available_functions(self, module_filter: Optional[str] = None) -> List[FunctionInfo]:
        """获取可用的函数列表"""
        if module_filter:
            return [func for key, func in self.function_index.items() 
                    if key.startswith(f"{module_filter}.")]
        return list(self.function_index.values())
    
    def get_available_classes(self, module_filter: Optional[str] = None) -> List[ClassInfo]:
        """获取可用的类列表"""
        if module_filter:
            return [cls for key, cls in self.class_index.items() 
                    if key.startswith(f"{module_filter}.")]
        return list(self.class_index.values())
    
    def suggest_imports(self, target_module: str, required_functions: List[str] = None, 
                       required_classes: List[str] = None) -> List[str]:
        """
        为指定模块生成导入建议
        
        Args:
            target_module: 目标模块名
            required_functions: 需要的函数列表
            required_classes: 需要的类列表
            
        Returns:
            List[str]: 导入语句列表
        """
        imports = []
        
        # 查找需要的函数和类
        if required_functions:
            for func_name in required_functions:
                func_info = self.find_function(func_name)
                if func_info:
                    source_module = os.path.splitext(os.path.basename(func_info.file_path))[0]
                    if source_module != target_module:
                        imports.append(f"from {source_module} import {func_info.name}")
        
        if required_classes:
            for cls_name in required_classes:
                cls_info = self.find_class(cls_name)
                if cls_info:
                    source_module = os.path.splitext(os.path.basename(cls_info.file_path))[0]
                    if source_module != target_module:
                        imports.append(f"from {source_module} import {cls_info.name}")
        
        return imports
    
    def generate_import_context(self, target_file: str) -> str:
        """
        为指定文件生成导入上下文提示
        
        Args:
            target_file: 目标文件路径
            
        Returns:
            str: 导入上下文提示文本
        """
        target_module = os.path.splitext(os.path.basename(target_file))[0]
        
        # 获取所有可用的函数和类
        available_functions = self.get_available_functions()
        available_classes = self.get_available_classes()
        
        # 过滤掉目标模块自身的定义
        external_functions = [f for f in available_functions 
                            if not f.file_path.endswith(target_file)]
        external_classes = [c for c in available_classes 
                          if not c.file_path.endswith(target_file)]
        
        if not external_functions and not external_classes:
            return ""
        
        context_parts = []
        
        if external_functions:
            context_parts.append("可重用的函数：")
            for func in external_functions[:5]:  # 限制数量避免过长
                source_module = os.path.splitext(os.path.basename(func.file_path))[0]
                params_str = ", ".join(func.parameters)
                return_str = f" -> {func.return_type}" if func.return_type else ""
                context_parts.append(f"  - {source_module}.{func.name}({params_str}){return_str}")
        
        if external_classes:
            context_parts.append("可重用的类：")
            for cls in external_classes[:3]:  # 限制数量
                source_module = os.path.splitext(os.path.basename(cls.file_path))[0]
                context_parts.append(f"  - {source_module}.{cls.name}")
        
        return "\n".join(context_parts)
    
    def get_project_structure_summary(self) -> str:
        """
        获取项目结构摘要，用于代码生成提示
        
        Returns:
            str: 项目结构摘要
        """
        if not self.project_structure.web_files:
            return "当前项目结构信息为空"
        
        summary_parts = ["项目结构摘要："]
        
        # 统计文件类型
        file_types = {}
        for web_info in self.project_structure.web_files.values():
            file_type = web_info.file_type
            file_types[file_type] = file_types.get(file_type, 0) + 1
        
        summary_parts.append(f"文件类型统计: {file_types}")
        
        # 显示目录结构
        summary_parts.append("目录结构：")
        for dir_path, files in self.project_structure.file_hierarchy.items():
            if files:
                summary_parts.append(f"  {dir_path}/")
                for file in files[:5]:  # 限制显示数量
                    summary_parts.append(f"    - {os.path.basename(file)}")
                if len(files) > 5:
                    summary_parts.append(f"    - ... 还有 {len(files) - 5} 个文件")
        
        # 显示常见的引用模式
        summary_parts.append("常见的路径模式：")
        for file_type, patterns in self.project_structure.path_patterns.items():
            summary_parts.append(f"  {file_type}文件: {', '.join(patterns)}")
        
        return "\n".join(summary_parts)
    
    def suggest_web_file_paths(self, target_file: str, file_type: str) -> List[str]:
        """
        为指定文件建议Web文件引用路径
        
        Args:
            target_file: 目标文件路径
            file_type: 需要引用的文件类型（css/js/images等）
            
        Returns:
            List[str]: 建议的路径列表
        """
        target_dir = os.path.dirname(target_file)
        suggestions = []
        
        # 基于项目结构中的现有文件建议
        for web_info in self.project_structure.web_files.values():
            if web_info.file_type == file_type:
                # 计算相对路径
                rel_path = os.path.relpath(web_info.file_path, target_dir)
                suggestions.append(rel_path)
        
        # 如果没有找到现有文件，使用常见的路径模式
        if not suggestions and file_type in self.project_structure.path_patterns:
            patterns = self.project_structure.path_patterns[file_type]
            for pattern in patterns:
                # 生成基于模式的建议路径
                if pattern.endswith('/'):
                    suggestions.append(f"{pattern}file.{file_type}")
                else:
                    suggestions.append(f"{pattern}/file.{file_type}")
        
        return suggestions[:5]  # 限制返回数量
    
    def generate_web_file_context(self, target_file: str) -> str:
        """
        为指定文件生成Web文件上下文提示
        
        Args:
            target_file: 目标文件路径
            
        Returns:
            str: Web文件上下文提示文本
        """
        target_ext = os.path.splitext(target_file)[1].lower()
        
        if target_ext not in ['.html', '.css', '.js']:
            return ""
        
        context_parts = []
        
        # 添加项目结构摘要
        structure_summary = self.get_project_structure_summary()
        if structure_summary != "当前项目结构信息为空":
            context_parts.append(structure_summary)
        
        # 根据文件类型添加特定建议
        if target_ext == '.html':
            context_parts.append("HTML文件引用建议：")
            
            # CSS文件引用建议
            css_suggestions = self.suggest_web_file_paths(target_file, 'css')
            if css_suggestions:
                context_parts.append("  CSS文件路径：")
                for suggestion in css_suggestions:
                    context_parts.append(f"    - {suggestion}")
            
            # JS文件引用建议
            js_suggestions = self.suggest_web_file_paths(target_file, 'js')
            if js_suggestions:
                context_parts.append("  JS文件路径：")
                for suggestion in js_suggestions:
                    context_parts.append(f"    - {suggestion}")
        
        elif target_ext == '.css':
            context_parts.append("CSS文件引用建议：")
            # 可以添加字体、图片等资源引用建议
            
        elif target_ext == '.js':
            context_parts.append("JS文件引用建议：")
            # 可以添加数据文件、其他JS模块引用建议
        
        return "\n".join(context_parts)
    
    def clear(self):
        """清空知识库"""
        self.modules.clear()
        self.function_index.clear()
        self.class_index.clear()
        self.import_dependencies.clear()
        
        # 清空Web文件相关数据
        self.web_files.clear()
        self.project_structure = ProjectStructure(
            web_files={},
            file_hierarchy={},
            path_patterns={
                'css': ['css/', 'styles/', 'assets/css/'],
                'js': ['js/', 'scripts/', 'assets/js/'],
                'images': ['images/', 'assets/images/', 'img/'],
                'data': ['data/', 'assets/data/']
            }
        )


# 全局代码知识库实例
code_knowledge_base = CodeKnowledgeBase()