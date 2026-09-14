from alembic import command
from alembic.config import Config

from forget_lah.seed import main as seed_main
from services.mock_clinic.bootstrap import main as mock_main


def main() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    seed_main()
    mock_main()


if __name__ == "__main__":
    main()
