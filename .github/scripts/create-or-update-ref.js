module.exports = async ({ github, context }, tagName) => {
  try {
    await github.rest.git.getRef({
      owner: context.repo.owner,
      repo: context.repo.repo,
      ref: `tags/${tagName}`,
    });

    await github.rest.git.updateRef({
      owner: context.repo.owner,
      repo: context.repo.repo,
      ref: `tags/${tagName}`,
      sha: context.sha,
      force: true,
    });
  } catch (err) {
    console.log(
      `⛔ Failed to update tag: ${tagName}. \n Attempting to create the tag ...`
    );
    console.log(err);
    try {
      await github.rest.git.createRef({
        owner: context.repo.owner,
        repo: context.repo.repo,
        ref: `refs/tags/${tagName}`,
        sha: context.sha,
        force: true,
      });
    } catch (err) {
      console.error(`⛔ Failed to create tag: ${tagName}`);
      console.error(err);
    }
  }
};
