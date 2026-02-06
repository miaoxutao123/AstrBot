#!/usr/bin/env python3
"""
Dashboard 前端构建和部署脚本

使用方法:
    python scripts/build_dashboard.py          # 构建并部署到 data/dist
    python scripts/build_dashboard.py --dev    # 仅启动开发服务器
    python scripts/build_dashboard.py --clean  # 清理构建产物

此脚本会:
1. 进入 dashboard 目录
2. 安装依赖 (如果需要)
3. 构建前端项目
4. 将构建产物复制到 data/dist 目录
"""

import argparse
import os
import shutil
import subprocess
import sys


def get_project_root():
    """获取项目根目录"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(script_dir)


def run_command(cmd, cwd=None, shell=False):
    """运行命令并实时输出"""
    print(f">>> 执行命令: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        shell=shell,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        print(f"命令执行失败，返回码: {result.returncode}")
        sys.exit(result.returncode)
    return result


def check_node_installed():
    """检查 Node.js 是否安装"""
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"Node.js 版本: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    print("错误: 未找到 Node.js，请先安装 Node.js")
    sys.exit(1)


def check_npm_installed():
    """检查 npm 是否安装"""
    try:
        result = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            shell=True if sys.platform == "win32" else False,
        )
        if result.returncode == 0:
            print(f"npm 版本: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    print("错误: 未找到 npm，请先安装 npm")
    sys.exit(1)


def install_dependencies(dashboard_dir):
    """安装依赖"""
    node_modules = os.path.join(dashboard_dir, "node_modules")
    package_json = os.path.join(dashboard_dir, "package.json")
    package_lock = os.path.join(dashboard_dir, "package-lock.json")

    # 检查是否需要安装依赖
    if os.path.exists(node_modules):
        # 检查 package.json 是否比 node_modules 新
        if os.path.exists(package_lock):
            pkg_mtime = os.path.getmtime(package_json)
            lock_mtime = os.path.getmtime(package_lock)
            modules_mtime = os.path.getmtime(node_modules)
            if pkg_mtime < modules_mtime and lock_mtime < modules_mtime:
                print("依赖已是最新，跳过安装")
                return

    print("正在安装依赖...")
    run_command(
        ["npm", "install"],
        cwd=dashboard_dir,
        shell=True if sys.platform == "win32" else False,
    )


def build_dashboard(dashboard_dir):
    """构建前端项目"""
    print("正在构建前端项目...")
    run_command(
        ["npm", "run", "build"],
        cwd=dashboard_dir,
        shell=True if sys.platform == "win32" else False,
    )


def deploy_to_data(dashboard_dir, project_root):
    """将构建产物部署到 data/dist 目录"""
    source_dist = os.path.join(dashboard_dir, "dist")
    target_dist = os.path.join(project_root, "data", "dist")

    if not os.path.exists(source_dist):
        print(f"错误: 构建产物目录不存在: {source_dist}")
        sys.exit(1)

    # 清理目标目录
    if os.path.exists(target_dist):
        print(f"清理目标目录: {target_dist}")
        shutil.rmtree(target_dist)

    # 复制构建产物
    print(f"复制构建产物到: {target_dist}")
    shutil.copytree(source_dist, target_dist)
    print("部署完成!")


def start_dev_server(dashboard_dir):
    """启动开发服务器"""
    print("启动开发服务器...")
    print("按 Ctrl+C 停止")
    try:
        run_command(
            ["npm", "run", "dev"],
            cwd=dashboard_dir,
            shell=True if sys.platform == "win32" else False,
        )
    except KeyboardInterrupt:
        print("\n开发服务器已停止")


def clean_build(dashboard_dir, project_root):
    """清理构建产物"""
    dirs_to_clean = [
        os.path.join(dashboard_dir, "dist"),
        os.path.join(dashboard_dir, "node_modules", ".vite"),
        os.path.join(project_root, "data", "dist"),
    ]

    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            print(f"清理: {dir_path}")
            shutil.rmtree(dir_path)

    print("清理完成!")


def main():
    parser = argparse.ArgumentParser(
        description="Dashboard 前端构建和部署脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python scripts/build_dashboard.py          # 构建并部署
    python scripts/build_dashboard.py --dev    # 启动开发服务器
    python scripts/build_dashboard.py --clean  # 清理构建产物
    python scripts/build_dashboard.py --no-install  # 跳过依赖安装
        """,
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="启动开发服务器而不是构建",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清理构建产物",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="跳过依赖安装",
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="只构建，不部署到 data/dist",
    )

    args = parser.parse_args()

    project_root = get_project_root()
    dashboard_dir = os.path.join(project_root, "dashboard")

    print(f"项目根目录: {project_root}")
    print(f"Dashboard 目录: {dashboard_dir}")

    if not os.path.exists(dashboard_dir):
        print(f"错误: Dashboard 目录不存在: {dashboard_dir}")
        sys.exit(1)

    # 检查 Node.js 和 npm
    check_node_installed()
    check_npm_installed()

    if args.clean:
        clean_build(dashboard_dir, project_root)
        return

    if args.dev:
        if not args.no_install:
            install_dependencies(dashboard_dir)
        start_dev_server(dashboard_dir)
        return

    # 正常构建流程
    if not args.no_install:
        install_dependencies(dashboard_dir)

    build_dashboard(dashboard_dir)

    if not args.no_deploy:
        deploy_to_data(dashboard_dir, project_root)

    print("\n✅ 前端构建完成!")
    print("现在可以启动 AstrBot 后端服务来查看更新后的前端页面")


if __name__ == "__main__":
    main()
