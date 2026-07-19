# Deploying the ExperienceOS demo to Alibaba Cloud

The demo is a single, stateful web server (the ledger lives in-process), so
it runs best on **one long-running instance** — an Alibaba Cloud **ECS**
VM — rather than serverless/Function Compute, which would fragment or lose
that in-memory state across instances.

The Qwen (DashScope) credential is **never** in the image or the repo. It is
injected at run time as the `QWEN_API_KEY` environment variable.

Container: `deploy/Dockerfile` (Python 3.12-slim, ~226 MB, zero third-party
deps). Server binds `0.0.0.0:8517` in the container.

---

## Recommended: ECS + Docker (clone & build on the box)

Pick a region that matches the DashScope endpoint the app uses
(`dashscope-intl.aliyuncs.com` → **Singapore** or another international
region). China-region accounts should set `QWEN_BASE_URL` to
`https://dashscope.aliyuncs.com/compatible-mode/v1` instead.

### 1. Create the instance (Alibaba Cloud console)

- **ECS → Create Instance**: Ubuntu 22.04, a small shape is plenty
  (e.g. 2 vCPU / 2–4 GB). Assign a **public IPv4** (or an EIP).
- **Security group**: allow inbound **TCP 80** (and 22 for SSH) from
  `0.0.0.0/0`. (Use 8517 instead of 80 if you prefer.)

### 2. Install Docker on the instance

```bash
ssh root@<ECS_PUBLIC_IP>
curl -fsSL https://get.docker.com | sh
```

### 3. Build and run

```bash
git clone https://github.com/bpolania/ExperienceOS.git
cd ExperienceOS
docker build -f deploy/Dockerfile -t experienceos-web .

# Inject the key at run time; map container 8517 -> host 80
docker run -d --name experienceos-web --restart unless-stopped \
  -p 80:8517 \
  -e QWEN_API_KEY='YOUR_DASHSCOPE_KEY' \
  experienceos-web
```

Judges open **`http://<ECS_PUBLIC_IP>/`**.

Verify:

```bash
curl -s http://<ECS_PUBLIC_IP>/api/state
# -> {"provider":"qwen","backend":"Alibaba Cloud DashScope","model":"qwen-plus",...}
```

---

## Alternative image transfer (no rebuild on the box)

If you'd rather not build on the instance, ship the local image:

```bash
docker save experienceos-web | gzip | \
  ssh root@<ECS_PUBLIC_IP> 'gunzip | docker load'
```

Then run the same `docker run …` as above.

---

## Container Registry route (ACR)

For a repeatable pipeline: push to **Alibaba Cloud Container Registry (ACR)**
and pull on the instance.

```bash
docker tag experienceos-web \
  registry-intl.<region>.aliyuncs.com/<namespace>/experienceos-web:latest
docker login registry-intl.<region>.aliyuncs.com   # ACR credentials
docker push registry-intl.<region>.aliyuncs.com/<namespace>/experienceos-web:latest
```

On ECS (or SAE / Function Compute custom-container), pull that image and run
it with `QWEN_API_KEY` set in the service's environment/secret configuration.

---

## Notes

- **Secret handling**: never commit `.env`; never `docker build` the key in.
  Set `QWEN_API_KEY` only via `-e` / the service's env-var or secret store.
  `.env` and caches are excluded by `.dockerignore`.
- **Public exposure**: a public URL backed by a live key means every visitor
  spends DashScope tokens. For a time-boxed demo that is normally fine; take
  the instance down afterwards (`docker rm -f experienceos-web`), or restrict
  the security group to known IPs.
- **HTTPS**: for a polished demo, put the instance behind an Alibaba Cloud
  SLB/ALB with a certificate, or run a small nginx + certbot in front. Plain
  HTTP on the public IP is enough for a functional demo.
- **State**: the ledger resets when the container restarts (in-memory by
  design). That is the intended demo behavior.
