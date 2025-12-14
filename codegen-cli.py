#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CodeGen CLI - 代码生成系统的命令行交互接口

使用方法：
    # 直接提供项目要求
    python codegen-cli.py "创建一个简单的待办事项应用"
    
    # 交互式输入
    python codegen-cli.py
    
    # 指定输出目录
    python codegen-cli.py "创建一个简单的待办事项应用" -o ./my-todo-app
    
    # 查看帮助
    python codegen-cli.py -h
"""

import os
import sys
import argparse
from orchestrator import Orchestrator

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description='CodeGen - AI驱动的代码生成系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
    # 直接生成代码
    python codegen-cli.py "创建一个简单的待办事项应用"
    
    # 交互式输入
    python codegen-cli.py
    
    # 指定输出目录
    python codegen-cli.py "创建一个简单的待办事项应用" -o ./my-todo-app
    
    # 使用特定模型
    python codegen-cli.py "创建一个简单的待办事项应用" -m qwen3-coder-plus
        """
    )
    
    # 位置参数：项目要求
    parser.add_argument(
        'task',
        nargs='?',
        help='项目要求描述（如果不提供，将进入交互式模式）。\n'+
             '提示：对于包含空格或换行的长描述，请使用引号包裹，例如：\n'+
             'python codegen-cli.py "创建一个待办事项应用\n要求：\n1. 支持添加任务\n2. 支持删除任务"'
    )
    
    # 可选参数
    parser.add_argument(
        '-o', '--output-dir',
        default='output',
        help='输出目录（默认：output）'
    )
    
    parser.add_argument(
        '-m', '--model',
        default=None,
        help='LLM模型名称（默认：qwen3-coder-plus）'
    )
    
    parser.add_argument(
        '--api-key',
        default=None,
        help='LLM API密钥（默认：从.env文件读取）'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='显示详细输出'
    )
    
    # 解析参数
    args = parser.parse_args()
    
    # 获取项目要求
    task = args.task
    
    # 如果未提供项目要求，进入交互式模式
    if not task:
        print("=" * 60)
        print("CodeGen - AI驱动的代码生成系统")
        print("=" * 60)
        print("请输入您的项目要求（支持多行输入）")
        
        print("结束输入方式：")
        print("另起新行输入 'EOF' 并按回车")
        
        print("按 Ctrl+C 可以随时退出")
        print("=" * 60)
        
        try:
            print("项目要求:")
            # 读取多行输入
            lines = []
            while True:
                line = input()
                # 检查特殊结束标记
                if line.strip() == 'EOF':
                    break
                lines.append(line)
        except EOFError:
            # 用户使用Ctrl+D或Ctrl+Z结束输入
            pass
        except KeyboardInterrupt:
            print("\n已取消")
            sys.exit(0)
        
        task = '\n'.join(lines).strip()
        if not task:
            print("\n错误：项目要求不能为空")
            sys.exit(1)
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    print(f"\n[CodeGen] 项目要求: {task}")
    print(f"[CodeGen] 输出目录: {args.output_dir}")
    print(f"[CodeGen] 正在初始化...")
    
    try:
        # 初始化 Orchestrator
        orchestrator = Orchestrator(
            output_dir=args.output_dir,
            llm_api_key=args.api_key,
            llm_model=args.model
        )
        
        print(f"[CodeGen] 开始生成代码...")
        print("=" * 60)
        
        # 执行任务
        orchestrator.run(task)
        
        print("=" * 60)
        print(f"[CodeGen] 代码生成完成！")
        print(f"[CodeGen] 生成的文件已保存到: {args.output_dir}")
        
        # 显示生成的文件
        print(f"\n[CodeGen] 生成的文件：")
        if os.path.exists(args.output_dir):
            for root, dirs, files in os.walk(args.output_dir):
                level = root.replace(args.output_dir, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    print(f"{subindent}{file}")
        
        print(f"\n[CodeGen] 您可以查看 {args.output_dir} 目录获取生成的代码。")
        print("[CodeGen] 祝您使用愉快！")
        
    except Exception as e:
        print(f"\n[CodeGen] 错误：{e}")
        print("[CodeGen] 请检查您的输入和配置，或查看日志获取更多信息。")
        sys.exit(1)

if __name__ == "__main__":
    main()
