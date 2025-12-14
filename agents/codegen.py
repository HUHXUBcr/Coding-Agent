import asyncio
import json
import re
from llm_client import LLMClient

CODEGEN_SYSTEM_PROMPT = """You are CodeGenerationAgent. You can use web_search tool to search for templates, examples, or documentation when needed.

CRITICAL INSTRUCTIONS:
- Return ONLY the raw code content - no explanations, no markdown formatting, no XML tags
- Do not include code blocks like ```python or ```
- Do not add comments about the code generation process
- Generate complete, runnable code files
- If you need to use web_search tool, the system will handle it automatically
- NEVER return tool call instructions like <function=web_search> in your response
- After tool results are provided, generate code directly using those results

FILE REFERENCE CONSISTENCY REQUIREMENTS:
- When generating files that reference other files, use CORRECT relative paths
- HTML files should reference CSS files as "css/style.css" (not "styles.css")
- HTML files should reference JS files as "js/script-name.js" (not "scripts.js")
- JS files should reference data files as "data/file-name.json" (not "/api/path")
- Always consider the project structure and file organization
- Ensure all file references are consistent across the entire project

Example of correct output:
def hello_world():
    print("Hello, World!")

hello_world()

NOT:
```python
def hello_world():
    print("Hello, World!")

hello_world()
```

NOT:
Here's the code you requested:
def hello_world():
    print("Hello, World!")

hello_world()"""

class CodeGenerationAgent:
    # 工具定义常量
    WEB_SEARCH_TOOL = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search for templates, examples, or documentation to use when you need to learn about a specific technology, framework, or best practice",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query keyword to find templates, examples, or documentation"
                    }
                },
                "required": ["query"]
            }
        }
    }

    def __init__(self, model="qwen3-coder-plus", api_key=None, code_knowledge_base=None):
        self.llm = LLMClient(model, api_key)
        self.tools = {}
        self.code_knowledge_base = code_knowledge_base

    def generate(self, file_info: dict, context: dict = None):
        """同步生成代码方法，支持qwen3自动判断是否调用工具"""
        return asyncio.run(self._generate_with_tools(file_info, context))

    async def _generate_with_tools(self, f, ctx):
        """使用工具调用功能的代码生成方法"""
        # 存储当前文件信息用于 fallback
        self.current_file_path = f.get('path', '')
        self.current_description = f.get('description', '')
        
        # 定义可用的工具
        tools = [self.WEB_SEARCH_TOOL]

        # 构建初始消息
        file_path = f.get('path', '')
        file_role = f.get('role', 'general')
        file_desc = f.get('description', '')
        
        # 根据文件类型提供更具体的指导
        file_type_hint = ""
        if file_path.endswith('.html'):
            file_type_hint = """Generate complete HTML5 document with proper DOCTYPE, head section (meta tags, title, CSS links), body with semantic tags, and script tags at the end. 

CRITICAL FILE REFERENCE REQUIREMENTS:
- Use RELATIVE paths for all file references based on the actual project structure
- CSS files should be referenced with correct relative paths (e.g., "css/style.css", "styles/main.css", "../assets/css/app.css")
- JS files should be referenced with correct relative paths (e.g., "js/script.js", "scripts/main.js", "../assets/js/app.js")
- IMPORTANT: JavaScript files must be loaded in correct dependency order:
  * Core logic files (paper-list.js) should be loaded BEFORE navigation files (navigation.js)
  * Utility files (citation-tools.js) should be loaded AFTER core logic files
  * Ensure script tags are ordered: core logic → navigation → utilities
- Image files should be referenced as "images/file-name.ext" or appropriate relative paths
- All paths must be relative and consistent with the project structure
- Ensure navigation links use correct relative paths like "detail.html?id=123" (NOT "/paper/123")
- IMPORTANT: Always check actual file names in the project and adapt references to match exactly"""
        elif file_path.endswith('.js'):
            file_type_hint = """Generate complete JavaScript with modern ES6+ syntax. Include proper DOM ready checks, error handling, and clear function names. 

FILE REFERENCE REQUIREMENTS:
- Data files should be referenced with correct relative paths (e.g., "data/file-name.json", "../data/config.json", "assets/data.json")
- HTML navigation MUST use correct relative paths like "detail.html?id=123" (NOT "/paper/123")
- If loading external data, support both flat arrays and nested objects with proper error handling
- IMPORTANT: Use relative paths that match the project structure, don't assume specific folder names"""
        elif file_path.endswith('.css'):
            file_type_hint = """Generate comprehensive CSS with reset rules, modern layout (flexbox/grid), responsive design, and clear organization with comments for sections.

FILE REFERENCE REQUIREMENTS:
- Use relative paths for background images based on project structure
- Ensure all selectors are consistent with HTML structure
- IMPORTANT: Adapt image paths to the actual project structure"""
        elif file_path.endswith('.json'):
            file_type_hint = (
                "Generate valid JSON data. For list-like data, prefer a top-level array of items, "
                "where each item is an object with fields like 'id', 'title', 'description', and optional "
                "'category', 'authors', 'time', 'link'. Only wrap the array in an extra object when the "
                "task explicitly requires that structure."
            )
        
        # 提取原始用户任务
        original_task = ctx.get('task_description', '') if ctx else ''
        
        # 获取代码知识库上下文（如果可用）
        code_knowledge_context = ""
        if self.code_knowledge_base and file_path.endswith('.py'):
            try:
                code_knowledge_context = ctx.get('code_knowledge_context', '')
                if code_knowledge_context:
                    code_knowledge_context = f"\nAVAILABLE CODE CONTEXT:\n{code_knowledge_context}"
            except Exception as e:
                print(f"[CodeGen] Warning: Failed to get code knowledge context: {e}")
        
        q = f"""
ORIGINAL USER TASK:
{original_task}

FILE TO GENERATE: {file_path}
FILE ROLE: {file_role}
DESCRIPTION: {file_desc}

GENERATION GUIDELINES:
{file_type_hint}

{code_knowledge_context}

CRITICAL: Generate code that DIRECTLY SOLVES the user's task above.
Do NOT generate generic examples or tutorials.
The code must be production-ready and specific to the task requirements.
Output ONLY the raw code content without explanations or markdown formatting.
"""
        
        messages = [
            {"role": "system", "content": CODEGEN_SYSTEM_PROMPT},
            {"role": "user", "content": q}
        ]

        # 第一次调用LLM
        assistant_output = await self.llm.chat(messages, tools=tools)
        messages.append(assistant_output)

        # 处理工具调用
        messages = await self._handle_tool_calls(messages, assistant_output, tools)
        
        # 提取最终代码
        if messages and messages[-1].get("role") == "assistant":
            return self._extract_pure_code(messages[-1].get("content", ""))
        elif messages and messages[-2].get("role") == "assistant":
            return self._extract_pure_code(messages[-2].get("content", ""))
        else:
            # 无需工具调用，直接返回结果
            return self._extract_pure_code(assistant_output.get("content", ""))
    
    def _extract_pure_code(self, content: str) -> str:
        """从LLM响应中提取纯代码内容，尽量少做破坏性处理"""
        if not content:
            return ""

        # 仅移除代码块标记
        content = re.sub(r'```[a-zA-Z]*\n?', '', content)
        content = re.sub(r'```\n?', '', content)

        lines = content.split('\n')

        # 跳过开头明显的解释性前缀
        skip_phrases = [
            'here is', 'here are', "here's",
            'the code', 'the following', 'below is',
            "i've generated", 'i have generated',
            'you can use', 'this code', 'code for'
        ]

        start = 0
        for i, line in enumerate(lines[:5]):
            line_lower = line.lower().strip()
            if any(p in line_lower for p in skip_phrases):
                start = i + 1
            else:
                # 一旦遇到不像解释的行，就认为后面都是代码
                break

        result = '\n'.join(lines[start:]).strip()
        return result if result else content.strip()

    async def _handle_tool_calls(self, messages, assistant_output, tools):
        """统一处理工具调用逻辑"""
        if "tool_calls" not in assistant_output or not assistant_output["tool_calls"]:
            return messages

        # 处理每个工具调用
        for tool_call in assistant_output["tool_calls"]:
            func_name = tool_call["function"]["name"]
            
            try:
                arguments = json.loads(tool_call["function"]["arguments"])
                
                if func_name == "web_search" and "web_search" in self.tools:
                    # 执行web搜索
                    print(f"[CodeGen] Web Search...")
                    search_result = self.tools["web_search"].search(arguments["query"])
                    result_content = str(search_result)
                else:
                    # 未知工具，返回空结果
                    result_content = "Tool not available"
                
                # 添加工具结果到消息
                tool_message = {
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": tool_call.get("id")
                }
                messages.append(tool_message)
            except Exception as e:
                # 工具调用失败，添加错误消息
                print(f"[CodeGen] Tool call failed: {e}")
                tool_message = {
                    "role": "tool",
                    "content": f"Error: {str(e)}",
                    "tool_call_id": tool_call.get("id")
                }
                messages.append(tool_message)
        
        # 再次调用LLM获取结果
        final_output = await self.llm.chat(messages, tools=tools)
        messages.append(final_output)
        
        # 检查是否还有工具调用
        if "tool_calls" in final_output and final_output["tool_calls"]:
            # 明确告诉LLM：不要再调用工具，直接生成代码
            print("[CodeGen] Warning: Multiple tool calls detected, requesting direct code generation")
            
            # 必须为所有tool_call添加response，否则API会报错
            for tool_call in final_output["tool_calls"]:
                messages.append({
                    "role": "tool",
                    "content": "Tool call limit reached. Please generate code directly without further tool calls.",
                    "tool_call_id": tool_call.get("id")
                })
            
            messages.append({
                "role": "user",
                "content": "Please generate the complete code file now. Do not call any more tools. Output the code directly."
            })
            final_output = await self.llm.chat(messages)
            messages.append(final_output)
        
        return messages
    
    def fix(self, old_content: str, review: dict):
        """同步修复代码方法，支持工具调用"""
        return asyncio.run(self._fix_with_tools(old_content, review))

    async def _fix_with_tools(self, old, review):
        """使用工具调用功能的代码修复方法"""
        # 使用统一的工具定义
        tools = [self.WEB_SEARCH_TOOL]

        # 从review中提取问题描述
        notes = review.get('notes', '')
        evaluation_info = review['evaluation']
        notes = ", ".join([f"{k}: {v}" for k, v in evaluation_info.items()])

        
        print(f"[CodeGen] Fix request - Issues to address: {notes[:200]}...")
        
        prompt = f"""Replace the following code:
        Issues to address: {notes}
        Original code: {old}
        
        If you need to search for bug fixes or best practices, you can use the web_search tool."""
        
        messages = [
            {"role": "system", "content": CODEGEN_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        assistant_output = await self.llm.chat(messages, tools=tools)
        messages.append(assistant_output)

        # 处理工具调用
        if "tool_calls" in assistant_output and assistant_output["tool_calls"]:
            print(f"[CodeGen] Processing {len(assistant_output['tool_calls'])} tool calls in fix")
            
        messages = await self._handle_tool_calls(messages, assistant_output, tools)
        
        # 提取最终代码
        if messages and messages[-1].get("role") == "assistant":
            extracted = self._extract_pure_code(messages[-1].get("content", ""))
        elif messages and messages[-2].get("role") == "assistant":
            extracted = self._extract_pure_code(messages[-2].get("content", ""))
        else:
            extracted = self._extract_pure_code(assistant_output.get("content", ""))
            print(f"[CodeGen] Extracted code length: {len(extracted)} bytes")
        return extracted
