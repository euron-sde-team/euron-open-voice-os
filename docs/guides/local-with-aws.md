# Local containers against real AWS

`make up-aws` runs the same containers as `make up` (`compose.yaml` plus
`compose.aws.yaml`), but against a real KMS key and S3 objects bucket instead of the
emulator. Postgres, Redis, the speech server, the runtime, TURN and the mock providers
stay local containers. Use it to check IAM, KMS and S3 behaviour that an emulator cannot
prove.

```bash
cd infra/terraform/envs/aws-dev && terraform apply -target=module.kms -target=module.storage
terraform output objects_bucket kms_key_alias
cd - && cp deploy/compose/.env.aws.example deploy/compose/.env.aws   # fill OBJECTS_BUCKET and KMS_KEY_ID from those outputs
make up-aws
```

`deploy/compose/.env.aws` (git-ignored) holds only resource names: `AWS_REGION`,
`OBJECTS_BUCKET`, `KMS_KEY_ID` and optionally `AWS_PROFILE`. Credentials come from your AWS
CLI profile (`AWS_PROFILE`, default `default`), with `~/.aws` mounted read-only into the
`migrate`, `api` and `worker` containers; no static keys are written anywhere.

The overlay sets `VOICEOS_CLOUD=aws`, `KEY_MODE=kms` and `STORAGE=s3`:

- provider API keys you add are sealed with KMS `Encrypt` under your key, with the
  encryption context `voiceos:record=<provider id>`;
- the API is configured for the bucket (`STORAGE=s3`); no 0.1.0 code path writes objects
  yet, so the bucket stays empty.

The stack still runs with `ENVIRONMENT=development`, so the production boot guards stay
off; leave `AWS_ENDPOINT_URL` unset so the SDK talks to real AWS. Your profile needs
`kms:Encrypt`, `kms:Decrypt` and `kms:GenerateDataKey` on the key. `make down` stops the containers; the AWS resources stay until
you `terraform destroy` them.
