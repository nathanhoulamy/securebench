# Fixture data for adversarial builders (not committed)

Some builders need the row's real reference/base file bytes (e.g. fix-git's
recovered site files, whose plaintext is the expected answer). To keep expected
answers out of the repo, these fixtures are git-ignored and regenerated from the
pinned upstream image.

## fix-git

    img="alexgshaw/fix-git@sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119"
    cid=$(docker create "$img")
    mkdir -p fix-git/reference fix-git/base
    # reference (recovered answer; == /app/resources/patch_files/*)
    docker cp $cid:/app/resources/patch_files/about.md      fix-git/reference/about.md
    docker cp $cid:/app/resources/patch_files/default.html  fix-git/reference/default.html
    # base (unfixed site files at master)
    docker cp $cid:/app/personal-site/_includes/about.md    fix-git/base/about.md
    docker cp $cid:/app/personal-site/_layouts/default.html fix-git/base/default.html
    docker rm $cid
