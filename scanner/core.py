import yaml, re, glob, json, pathlib, requests

RULES_DIR = pathlib.Path(__file__).resolve().parent.parent / "rules"

def load_rules():
    rules = []
    for fp in RULES_DIR.glob("*.json"):
        rules.append(json.loads(fp.read_text()))
    return rules

def load_workflows(repo_path="."):
    pattern = pathlib.Path(repo_path) / ".github" / "workflows" / "*.y*ml"
    for fp in glob.glob(str(pattern)):
        with open(fp, 'r') as f:
            content = yaml.safe_load(f)
            yield fp, content

def scan(repo_path="."):
    """Scan local repository for vulnerabilities"""
    rules = load_rules()
    findings = []
    
    for file_path, workflow in load_workflows(repo_path):
        findings.extend(check_workflow_security(workflow, file_path))
    
    return findings

def scan_remote_repo(repo_name, token=None):
    """Scan a remote GitHub repository"""
    findings = []
    headers = {'Authorization': f'token {token}'} if token else {}
    
    # Get workflow files from GitHub API
    url = f"https://api.github.com/repos/{repo_name}/contents/.github/workflows"
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 404:
            print(f"Repository {repo_name} not found or no workflows directory")
            return findings
        elif response.status_code != 200:
            print(f"Error accessing {repo_name}: {response.status_code}")
            return findings
        
        files = response.json()
        for file_info in files:
            if file_info['name'].endswith(('.yml', '.yaml')):
                # Download file content
                content_response = requests.get(file_info['download_url'])
                if content_response.status_code == 200:
                    try:
                        workflow = yaml.safe_load(content_response.text)
                        findings.extend(check_workflow_security(workflow, file_info['name']))
                    except Exception as e:
                        print(f"Warning: Could not parse {file_info['name']}: {e}")
    
    except requests.RequestException as e:
        print(f"Network error: {e}")
    
    return findings

def scan_organization(org_name, token=None, max_repos=50):
    """Scan entire GitHub organization"""
    all_findings = []
    headers = {'Authorization': f'token {token}'} if token else {}
    
    # Get repositories from organization
    url = f"https://api.github.com/orgs/{org_name}/repos"
    params = {'per_page': max_repos, 'type': 'public'}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Error accessing organization {org_name}: {response.status_code}")
            return all_findings
        
        repos = response.json()
        print(f"Scanning {len(repos)} repositories in {org_name}...")
        
        for repo in repos:
            repo_name = f"{org_name}/{repo['name']}"
            print(f"Scanning {repo_name}...")
            findings = scan_remote_repo(repo_name, token)
            all_findings.extend(findings)
    
    except requests.RequestException as e:
        print(f"Network error: {e}")
    
    return all_findings

def check_workflow_security(workflow, file_path):
    """Apply all security checks to a workflow"""
    findings = []
    
    # Check pull_request_target
    if isinstance(workflow.get('on'), dict) and 'pull_request_target' in workflow['on']:
        findings.append({
            "rule": "GHA002",
            "desc": "Workflow triggered by pull_request_target (risky for external forks)",
            "severity": "medium",
            "file": pathlib.Path(file_path).name,
            "loc": "on.pull_request_target",
            "value": "pull_request_target"
        })
    elif isinstance(workflow.get('on'), list) and 'pull_request_target' in workflow['on']:
        findings.append({
            "rule": "GHA002", 
            "desc": "Workflow triggered by pull_request_target (risky for external forks)",
            "severity": "medium",
            "file": pathlib.Path(file_path).name,
            "loc": "on",
            "value": "pull_request_target"
        })
    
    # Check jobs
    for job_name, job in workflow.get('jobs', {}).items():
        for step_idx, step in enumerate(job.get('steps', [])):
            
            # Check for unpinned actions
            if 'uses' in step:
                uses_value = step['uses']
                if re.search(r'@(v\d+|latest)$', uses_value):
                    findings.append({
                        "rule": "GHA001",
                        "desc": "Action version not pinned to commit SHA",
                        "severity": "high", 
                        "file": pathlib.Path(file_path).name,
                        "loc": f"jobs.{job_name}.steps[{step_idx}].uses",
                        "value": uses_value
                    })
            
            # Check for secret leakage
            if 'run' in step:
                run_value = step['run']
                if re.search(r'echo.*\$\{\{\s*secrets\.', run_value, re.DOTALL):
                    findings.append({
                        "rule": "GHA003",
                        "desc": "Potential secret leakage via echo",
                        "severity": "high",
                        "file": pathlib.Path(file_path).name, 
                        "loc": f"jobs.{job_name}.steps[{step_idx}].run",
                        "value": run_value.replace('\n', ' ')[:60] + "..."
                    })
    
    # Apply advanced checks
    findings.extend(check_self_hosted_runners(workflow, file_path))
    findings.extend(check_missing_permissions(workflow, file_path))
    findings.extend(check_cache_poisoning(workflow, file_path))
    
    return findings

def check_self_hosted_runners(workflow, file_path):
    """Detect self-hosted runners on public repos"""
    findings = []
    for job_name, job in workflow.get('jobs', {}).items():
        runs_on = job.get('runs-on', '')
        if isinstance(runs_on, str) and 'self-hosted' in runs_on:
            findings.append({
                "rule": "GHA004",
                "desc": "Self-hosted runners on public repository (infrastructure exposure risk)",
                "severity": "critical",
                "file": pathlib.Path(file_path).name,
                "loc": f"jobs.{job_name}.runs-on",
                "value": runs_on
            })
        elif isinstance(runs_on, list) and any('self-hosted' in str(runner) for runner in runs_on):
            findings.append({
                "rule": "GHA004",
                "desc": "Self-hosted runners on public repository (infrastructure exposure risk)", 
                "severity": "critical",
                "file": pathlib.Path(file_path).name,
                "loc": f"jobs.{job_name}.runs-on",
                "value": str(runs_on)
            })
    return findings

def check_missing_permissions(workflow, file_path):
    """Check for workflows without explicit permissions"""
    findings = []
    
    # Check if workflow has any permissions defined
    if 'permissions' not in workflow:
        findings.append({
            "rule": "GHA005",
            "desc": "Workflow missing explicit permissions (principle of least privilege violation)",
            "severity": "medium", 
            "file": pathlib.Path(file_path).name,
            "loc": "permissions",
            "value": "undefined (defaults to read-all)"
        })
    else:
        # Check for overly broad permissions
        perms = workflow.get('permissions', {})
        if perms == {} or perms.get('contents') == 'write':
            findings.append({
                "rule": "GHA005",
                "desc": "Workflow has overly broad permissions",
                "severity": "medium",
                "file": pathlib.Path(file_path).name, 
                "loc": "permissions",
                "value": str(perms)
            })
    
    return findings

def check_cache_poisoning(workflow, file_path):
    """Detect cache configurations vulnerable to poisoning"""
    findings = []
    
    for job_name, job in workflow.get('jobs', {}).items():
        for step_idx, step in enumerate(job.get('steps', [])):
            if 'uses' in step and 'cache' in step['uses']:
                # Check for cache actions without proper key scoping
                if 'with' in step:
                    cache_key = step['with'].get('key', '')
                    if not re.search(r'\$\{\{\s*runner\.os\s*\}\}', cache_key):
                        findings.append({
                            "rule": "GHA008",
                            "desc": "Cache key missing OS isolation (poisoning risk)",
                            "severity": "high",
                            "file": pathlib.Path(file_path).name,
                            "loc": f"jobs.{job_name}.steps[{step_idx}].with.key",
                            "value": cache_key
                        })
    
    return findings
