"""SSH deploy utility — write config to proxy server via SSH key auth."""

import asyncio
import logging
import os
import shlex
import tempfile

logger = logging.getLogger("pve2proxy.deployer")


def _ssh_base_args(port: int, key_path: str, scp: bool = False) -> list[str]:
    # ssh uses -p for port; scp uses -P (lowercase -p means "preserve times")
    port_flag = "-P" if scp else "-p"
    return [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=/dev/null",
        port_flag, str(port),
        "-i", key_path,
    ]


async def _write_temp(content: str) -> tuple[str, str]:
    """Write content to a temp file. Returns (path, dir)."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
    f.write(content)
    f.close()
    os.chmod(f.name, 0o644)
    return f.name


async def ssh_write(host: str, port: int, user: str, key: str,
                    remote_path: str, content: str) -> tuple[bool, str]:
    """Write content to remote file via SSH using key-based auth.

    Uses scp to transfer + ssh to move into place.
    Returns (success, message_or_error).
    """
    if not host or not user or not key:
        return False, "SSH host, user and key are required"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
        f.write(key)
        key_path = f.name
    os.chmod(key_path, 0o600)

    local_tmp = None
    try:
        local_tmp = await _write_temp(content)
        remote_tmp = f"/var/tmp/pve2proxy_{os.urandom(4).hex()}"
        dest = f"{user}@{host}:{remote_tmp}"
        scp_cmd = ["scp"] + _ssh_base_args(port, key_path, scp=True) + [local_tmp, dest]
        proc = await asyncio.create_subprocess_exec(
            *scp_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return False, stderr.decode().strip() or f"SCP exit code {proc.returncode}"

        parent = shlex.quote(os.path.dirname(remote_path))
        rpath_q = shlex.quote(remote_path)
        mv_cmd = ["ssh"] + _ssh_base_args(port, key_path) + [
            f"{user}@{host}",
            f"mkdir -p {parent} && mv {remote_tmp} {rpath_q} && chmod 644 {rpath_q}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *mv_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return False, stderr.decode().strip() or f"Move failed with code {proc.returncode}"

        return True, f"Written to {remote_path}"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(key_path)
        except Exception:
            pass
        if local_tmp:
            try:
                os.unlink(local_tmp)
            except Exception:
                pass


async def ssh_run(host: str, port: int, user: str, key: str,
                  command: str) -> tuple[bool, str]:
    """Run a command on the remote host via SSH.

    Returns (success, output_or_error).
    """
    if not host or not user or not key:
        return False, "SSH host, user and key are required"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
        f.write(key)
        key_path = f.name
    os.chmod(key_path, 0o600)

    try:
        cmd = ["ssh"] + _ssh_base_args(port, key_path) + [f"{user}@{host}", command]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return False, stderr.decode().strip() or f"Exit code {proc.returncode}"
        return True, stdout.decode().strip()
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(key_path)
        except Exception:
            pass


async def ssh_test(host: str, port: int, user: str, key: str) -> tuple[bool, str]:
    """Test SSH connection to the proxy server."""
    ok, out = await ssh_run(host, port, user, key, "echo pve2proxy_ok")
    if ok and "pve2proxy_ok" in out:
        return True, "SSH connection successful"
    return ok, out


async def deploy_config(provider_type: str, config: dict,
                        mappings: list[dict]) -> dict:
    """Generate and deploy config to the proxy server.

    1. Generates config string from provider
    2. SSH-writes to the remote path
    3. Runs reload command if applicable
    """
    from .providers import create_providers

    if not config.get("ssh_host"):
        return {"status": "error", "message": "SSH host not configured"}

    provider = create_providers(config)
    config_str = provider.generate(mappings, config)
    output_path = provider.get_output_path(config)

    ok, msg = await ssh_write(
        host=config["ssh_host"],
        port=config.get("ssh_port", 22),
        user=config.get("ssh_user", "root"),
        key=config.get("ssh_key", ""),
        remote_path=output_path,
        content=config_str,
    )
    if not ok:
        return {"status": "error", "message": f"Deploy failed: {msg}"}

    reload_cmd = provider.get_reload_command(config)
    if reload_cmd:
        ok, msg = await ssh_run(
            host=config["ssh_host"],
            port=config.get("ssh_port", 22),
            user=config.get("ssh_user", "root"),
            key=config.get("ssh_key", ""),
            command=reload_cmd,
        )
        if not ok:
            return {"status": "warning", "message": f"Config written but reload failed: {msg}",
                    "config": config_str}

    return {"status": "success", "message": "Config deployed and service reloaded",
            "config": config_str}
