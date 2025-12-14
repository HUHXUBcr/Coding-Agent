import json
import re
import asyncio
from llm_client import LLMClient

PLANNER_SYSTEM_PROMPT = """You are a project planning expert. Analyze tasks and generate structured plans.

Output ONLY valid JSON in this exact format:

{
  "task_list": [
    {
      "task": "task description",
      "files": [
        {
          "path": "relative/path/to/file.ext",
          "description": "what this file does",
          "role": "data/view/logic/style/entry_point"
        }
      ]
    }
  ],
  "estimated_time": "X hours",
  "priority": "high/medium/low"
}

IMPORTANT:
- Use exact file paths (e.g., "data/papers.json" not "data file")
- Infer data structure from task requirements
- Group related files into logical tasks
- Return ONLY the JSON, no explanations"""

class ProjectPlanningAgent:
    def __init__(self, model="qwen3-235b-a22b-thinking-2507", api_key=None):
        self.llm = LLMClient(model, api_key)
        self.tools = {}

    def plan(self, task_text: str):
        """同步调用计划方法"""
        # Web search enhancement - 使用LLM提取搜索关键词
        if "web_search" in self.tools:
            search_query = asyncio.run(self._extract_search_keywords(task_text))
            
            if search_query:
                print(f"[Planner] Searching web for: {search_query}")
                info = self.tools["web_search"].search(search_query, top_k=3)
                
                if info and len(info) > 0:
                    task_text += "\n\nSearchContext: " + str(info)
                    print(f"[Planner] Found {len(info)} search results")
                else:
                    print("[Planner] No search results found, proceeding without search context")
            else:
                print("[Planner] Failed to extract search keywords, skipping web search")

        return asyncio.run(self._plan_async(task_text))
    
    async def _extract_search_keywords(self, task_text: str) -> str:
        """使用LLM从任务描述中提取搜索关键词"""
        extraction_prompt = f"""Extract key search terms from the following task description for web search. 
        Return ONLY the search query (maximum 200 words, keep it concise), no explanation.
        Task: {task_text}"""
        
        try:
            messages = [
                {"role": "system", "content": "You are a search query extraction assistant. Extract concise, relevant search terms from user tasks."},
                {"role": "user", "content": extraction_prompt}
            ]
            
            response = await self.llm.chat(messages)
            keywords = response.get("content", "").strip()
            
            # 清理可能的额外文本
            keywords = keywords.replace("Search keywords:", "").strip()
            keywords = keywords.replace("Keywords:", "").strip()
            
            # 检查是否超过400字符（Brave API限制）
            if len(keywords) > 400:
                print(f"[Planner] Keywords too long ({len(keywords)} chars), requesting shorter version...")
                
                # 给LLM第二次机会，明确要求更短
                retry_prompt = f"""The previous keywords were too long. Extract ONLY the most essential search terms (maximum 100 words, under 400 characters).
                Task: {task_text}
                Essential search keywords (be extremely concise):"""
                
                messages.append(response)
                messages.append({"role": "user", "content": retry_prompt})
                
                retry_response = await self.llm.chat(messages)
                keywords = retry_response.get("content", "").strip()
                keywords = keywords.replace("Search keywords:", "").strip()
                keywords = keywords.replace("Keywords:", "").strip()
                keywords = keywords.replace("Essential search keywords:", "").strip()
                
                # 如果还是太长，强制截取
                if len(keywords) > 400:
                    print(f"[Planner] Still too long ({len(keywords)} chars), truncating to 400...")
                    keywords = keywords[:397] + "..."
            
            return keywords if keywords else task_text[:400]
            
        except Exception as e:
            print(f"[Planner] Keyword extraction failed: {str(e)}, using fallback")
            # 失败时使用简单截取前400字符作为备选
            return task_text[:400].strip() if len(task_text) > 400 else task_text.strip()

    async def _plan_async(self, t):
        # 简化prompt，直接要求生成计划
        user_prompt = f"""Generate a project plan for this task:

{t}

Break it into logical tasks with specific files. Include appropriate file types based on the task:
- For web projects: HTML, CSS, JavaScript, JSON files
- For Python projects: Python scripts/modules
- For data projects: Data files, processing scripts
- Other: Any relevant file types

Use exact paths like "data/items.json", "js/main.js", "css/style.css", "main.py", "utils/helpers.py".

Return ONLY the JSON plan, no other text."""

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        # 使用流式思维链推理模型
        response = await self.llm.chat(messages)
        
        # 提取内容并验证JSON格式
        content = response.get("content", "")
        
        # 尝试多种方式解析JSON
        try:
            plan_data = json.loads(content)
            return self._validate_plan_format(plan_data)
        except json.JSONDecodeError:
            print("[Planner] Direct JSON parse failed, trying extraction...")
            
            # 方法1: 提取```json代码块
            json_block_match = re.search(r'```json\s*([\s\S]*?)```', content)
            if json_block_match:
                try:
                    plan_data = json.loads(json_block_match.group(1))
                    print("[Planner] Extracted JSON from code block")
                    return self._validate_plan_format(plan_data)
                except:
                    pass
            
            # 方法2: 提取第一个完整的{...}对象
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    plan_data = json.loads(json_match.group())
                    print("[Planner] Extracted JSON from response text")
                    return self._validate_plan_format(plan_data)
                except Exception as e:
                    print(f"[Planner] JSON extraction failed: {e}")
            
            # 如果所有方法都失败，使用默认结构
            print("[Planner] Using fallback default plan")
            return self._get_default_plan(t)
    
    def _validate_plan_format(self, plan_data: dict) -> dict:
        """验证计划格式，确保符合通信协议要求"""
        # 确保有task_list字段
        if "task_list" not in plan_data:
            plan_data["task_list"] = []
        
        # 确保每个任务都有正确的结构
        for task in plan_data["task_list"]:
            if "task" not in task:
                task["task"] = "Unknown task"
            if "files" not in task:
                task["files"] = []
        
        # 添加默认字段
        if "estimated_time" not in plan_data:
            plan_data["estimated_time"] = "Unknown"
        if "priority" not in plan_data:
            plan_data["priority"] = "medium"
        if "dependencies" not in plan_data:
            plan_data["dependencies"] = []
        
        return plan_data
    
    def _get_default_plan(self, task_text: str) -> dict:
        """获取默认计划结构，根据任务类型智能推断，包含完整项目规范
        
        注意：这是fallback机制，只在LLM规划失败时使用。
        不包含任何特定业务逻辑，只提供通用的web项目结构框架。
        """
        task_lower = task_text.lower()
        
        # 检测是否为web项目
        web_indicators = ['webpage', 'website', 'html', 'css', 'javascript', 'frontend', 'web app', 'navigation', 'responsive']
        is_web_project = any(indicator in task_lower for indicator in web_indicators)
        
        if is_web_project:
            # Web项目的默认结构 - 提供更详细的描述以帮助codegen生成正确的代码
            return {
                "task_list": [
                    {
                        "task": "Create main HTML page with navigation and content display",
                        "files": [
                            {"path": "index.html", "description": "Main homepage with header navigation, hero section, and dynamic content container. Include proper HTML5 structure with semantic tags. Reference css/style.css and js/main.js", "role": "entry_point"},
                            {"path": "css/style.css", "description": "Main stylesheet with reset, header styles, navigation, layout grid, and responsive design. Use modern CSS with flexbox/grid.", "role": "styling"},
                            {"path": "js/main.js", "description": "Main JavaScript file to load data from JSON, render items dynamically into container, handle navigation interactions. Use modern ES6+ syntax.", "role": "functionality"}
                        ]
                    },
                    {
                        "task": "Create detail page for individual items", 
                        "files": [
                            {"path": "detail.html", "description": "Detail page template with back navigation, title display area, and content section. Parse URL parameters to load specific item. Reference css/style.css and js/detail-page.js", "role": "detail_view"},
                            {"path": "js/detail-page.js", "description": "Load item details from JSON based on URL parameter 'id', display in page, handle errors gracefully. Support nested data structures (e.g., data.items, data.papers).", "role": "detail_functionality"}
                        ]
                    },
                    {
                        "task": "Create sample data files",
                        "files": [
                            {
                                "path": "data/papers.json",
                                "description": "Sample data in JSON format. Use a top-level array of items. Each item is an object with fields like 'id', 'title', 'description', and optional 'category', 'authors', 'time', 'link'. This file acts as a generic list data source.",
                                "role": "data"
                            }
                        ]
                    }
                ],
                "estimated_time": "2-3 hours",
                "priority": "high",
                "dependencies": []
            }
        else:
            # Python项目的默认结构
            return {
                "task_list": [
                    {
                        "task": task_text,
                        "files": [
                            {"path": "main.py", "description": "Main application file"}
                        ]
                    }
                ],
                "estimated_time": "Unknown",
            "priority": "medium",
            "dependencies": []
        }
