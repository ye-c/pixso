from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Confirm
from rich.table import Table

from .exif import PixExif

console = Console()


class Syncer:
    def __init__(self, target_dir: str, dry_run: bool = False):
        self.target_dir = Path(target_dir)
        self.dry_run = dry_run

    def run(self):
        console.print(
            f"[bold blue]Scanning {self.target_dir} for normalization...[/bold blue]"
        )

        files_to_sync = []
        if self.target_dir.is_file():
            files_to_sync.append(self.target_dir)
        else:
            extensions = PixExif._IMAGES | PixExif._VIDEOS
            for ext in extensions:
                for f in self.target_dir.rglob(f"*{ext}"):
                    if (
                        not f.name.startswith("._")
                        and not f.name.startswith(".")
                        and "duplicates" not in f.parts
                    ):
                        files_to_sync.append(f)
                for f in self.target_dir.rglob(f"*{ext.upper()}"):
                    if (
                        not f.name.startswith("._")
                        and not f.name.startswith(".")
                        and "duplicates" not in f.parts
                    ):
                        files_to_sync.append(f)

        if not files_to_sync:
            console.print("[green]No files found to sync.[/green]")
            return

        actions = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            MofNCompleteColumn(),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "[cyan]Analyzing files: ", total=len(files_to_sync)
            )

            for file_path in files_to_sync:
                try:
                    exif = PixExif(file_path)
                    new_name = exif.rename()

                    if file_path.name != new_name:
                        actions.append((file_path, file_path.parent / new_name))
                except Exception as e:
                    console.print(
                        f"[yellow]Warning: Failed to parse {file_path.name}: {e}[/yellow]"
                    )

                progress.advance(task)

        if not actions:
            console.print("[green]All files are already normalized![/green]")
            return

        table = Table(title=f"Files to Normalize ({len(actions)})")
        table.add_column("Original Name", style="cyan")
        table.add_column("New Name", style="magenta")

        # Show first 50 to avoid overwhelming terminal
        for old_path, new_path in actions[:50]:
            table.add_row(old_path.name, new_path.name)

        if len(actions) > 50:
            table.add_row("...", f"... and {len(actions) - 50} more files")

        console.print(table)

        if self.dry_run:
            console.print(
                "[yellow]Dry run mode enabled. No files will be modified.[/yellow]"
            )
            return

        if not Confirm.ask("Do you want to proceed with normalization?"):
            console.print("Operation cancelled.")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            MofNCompleteColumn(),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Renaming files: ", total=len(actions))

            for old_path, new_path in actions:
                try:
                    # Handle case where target already exists
                    if new_path.exists() and old_path != new_path:
                        stem = new_path.stem
                        suffix = new_path.suffix
                        counter = 1
                        while True:
                            collision_path = (
                                new_path.parent / f"{stem}_{counter}{suffix}"
                            )
                            if not collision_path.exists():
                                new_path = collision_path
                                break
                            counter += 1

                    old_path.rename(new_path)
                except Exception as e:
                    console.print(f"[red]Error renaming {old_path.name}: {e}[/red]")

                progress.advance(task)

        console.print(
            "[bold green]Normalization complete! You should run `px dedupe` next.[/bold green]"
        )
