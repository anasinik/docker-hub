from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from repositories.services.registry.auth import generate_key_pair


class Command(BaseCommand):
    help = (
        "Create the RSA key that signs registry tokens (REGISTRY_TOKEN_PRIVATE_KEY_PATH) "
        "and the certificate the registry uses to verify them (token.crt next to the key)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing files. Tokens signed with the old key stop working.",
        )

    def handle(self, *args, **options):
        key_path = settings.REGISTRY_TOKEN_PRIVATE_KEY_PATH
        cert_path = key_path.with_name("token.crt")

        existing = [path for path in (key_path, cert_path) if path.exists()]
        if existing and not options["force"]:
            raise CommandError(
                f"{', '.join(str(path) for path in existing)} already exists. Use --force to replace."
            )

        key_pem, cert_pem = generate_key_pair(settings.REGISTRY_TOKEN_ISSUER)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key_pem)
        key_path.chmod(0o600)
        cert_path.write_bytes(cert_pem)

        self.stdout.write(self.style.SUCCESS(f"Private key: {key_path}"))
        self.stdout.write(self.style.SUCCESS(f"Certificate: {cert_path}"))
        self.stdout.write("Restart the registry container so it loads the new certificate.")
