import click
import os
from rich.table import Table
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from scanner.core import scan, scan_remote_repo, scan_organization

console = Console()

@click.command()
@click.option("--path", "-p", default=".", help="Local repository path")
@click.option("--repo", "-r", help="Remote GitHub repo (owner/name)")
@click.option("--org", "-o", help="Scan entire GitHub organization")
@click.option("--token", "-t", help="GitHub Personal Access Token (or set GITHUB_TOKEN env var)")
@click.option("--output", default="table", help="Output format: table/json/csv")
@click.option("--severity", help="Filter by severity: critical/high/medium/low")
@click.option("--max-repos", default=50, help="Maximum repositories to scan in organization")
def main(path, repo, org, token, output, severity, max_repos):
    """GitHub Actions Security Scanner - Detect CI/CD vulnerabilities"""
    
    # Get token from environment if not provided
    if not token:
        token = os.getenv('GITHUB_TOKEN')
    
    if org:
        if not token:
            console.print("[red]Error: GitHub token required for organization scanning[/red]")
            console.print("Set GITHUB_TOKEN environment variable or use --token flag")
            return
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(f"Scanning organization {org}...", total=None)
            findings = scan_organization(org, token, max_repos)
        
        display_results(findings, f"Organization: {org}", output, severity)
        
    elif repo:
        if not token:
            console.print("[yellow]Warning: No GitHub token provided. Rate limits may apply.[/yellow]")
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(f"Scanning repository {repo}...", total=None)
            findings = scan_remote_repo(repo, token)
        
        display_results(findings, f"Remote repo: {repo}", output, severity)
        
    else:
        findings = scan(path)
        display_results(findings, f"Local path: {path}", output, severity)

def display_results(findings, source, output_format="table", severity_filter=None):
    """Display scan results in specified format"""
    
    # Apply severity filter
    if severity_filter:
        findings = [f for f in findings if f['severity'] == severity_filter.lower()]
    
    if not findings:
        console.print(f"[green]✅ No risky patterns found in {source}[/green]")
        return
    
    if output_format == "json":
        import json
        print(json.dumps(findings, indent=2))
        return
    elif output_format == "csv":
        print("Rule,Severity,File,Location,Value")
        for f in findings:
            print(f"{f['rule']},{f['severity']},{f['file']},{f['loc']},{f['value']}")
        return
    
    # Default table format
    tbl = Table(title=f"GitHub Actions Scan Results - {source}")
    tbl.add_column("Rule", style="bold")
    tbl.add_column("Severity")
    tbl.add_column("File", style="cyan")
    tbl.add_column("Location", style="dim")
    tbl.add_column("Value", max_width=40)
    
    sev_color = {
        "critical": "bold red",
        "high": "red", 
        "medium": "yellow",
        "low": "cyan"
    }
    
    for f in findings:
        tbl.add_row(
            f["rule"],
            f"[{sev_color[f['severity']]}]{f['severity']}[/]",
            f["file"],
            f["loc"],
            f["value"][:50] + "..." if len(f["value"]) > 50 else f["value"]
        )
    
    console.print(tbl)
    
    # Enhanced statistics
    stats = {}
    for f in findings:
        stats[f['severity']] = stats.get(f['severity'], 0) + 1
    
    console.print(f"\n📊 **Scan Summary:**")
    if 'critical' in stats:
        console.print(f"• [bold red]{stats['critical']}[/] critical issues")
    if 'high' in stats:
        console.print(f"• [red]{stats['high']}[/] high severity issues")
    if 'medium' in stats:
        console.print(f"• [yellow]{stats['medium']}[/] medium severity issues")
    if 'low' in stats:
        console.print(f"• [cyan]{stats['low']}[/] low severity issues")
    
    console.print(f"• [bold]{len(findings)}[/] total vulnerabilities detected")

@click.command()
@click.option("--token", "-t", help="GitHub Personal Access Token")
def scan_popular_repos(token):
    """Scan popular repositories for demonstration"""
    popular_repos = [
        "microsoft/vscode",
        "facebook/react", 
        "vuejs/vue",
        "angular/angular",
        "nodejs/node"
    ]
    
    all_findings = []
    for repo in popular_repos:
        console.print(f"[blue]Scanning {repo}...[/blue]")
        findings = scan_remote_repo(repo, token)
        all_findings.extend(findings)
    
    display_results(all_findings, f"{len(popular_repos)} popular repositories")

if __name__ == "__main__":
    main()
