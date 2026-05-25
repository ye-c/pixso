import typer

from .exif import PixExif

app = typer.Typer(help="图片/视频元数据处理工具")


@app.command()
def process(path: str):
    """处理单个文件"""
    try:
        exif = PixExif(path)
        typer.echo(exif.rename())
    except Exception as e:
        typer.echo(f"错误: {e}", err=True)
        raise typer.Exit(1)


def main():
    """主入口函数"""
    app()


if __name__ == "__main__":
    main()
