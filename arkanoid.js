const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');
const scoreElement = document.getElementById('score');
const livesElement = document.getElementById('lives');
const messageScreen = document.getElementById('message-screen');
const messageText = document.getElementById('message-text');
const playAgainButton = document.getElementById('play-again');

let score = 0;
let lives = 3;
let gameOver = false;

const paddle = {
    x: canvas.width / 2 - 50,
    y: canvas.height - 20,
    width: 100,
    height: 10,
    speed: 8,
    dx: 0
};

const ball = {
    x: canvas.width / 2,
    y: canvas.height - 30,
    size: 7,
    speed: 4,
    dx: 4,
    dy: -4
};

const brickInfo = {
    width: 75,
    height: 20,
    padding: 10,
    offsetX: 45,
    offsetY: 60,
    rows: 5,
    cols: 8
};

let bricks = [];

function createBricks() {
    bricks = [];
    for (let c = 0; c < brickInfo.cols; c++) {
        bricks[c] = [];
        for (let r = 0; r < brickInfo.rows; r++) {
            const x = c * (brickInfo.width + brickInfo.padding) + brickInfo.offsetX;
            const y = r * (brickInfo.height + brickInfo.padding) + brickInfo.offsetY;
            bricks[c][r] = { x, y, visible: true };
        }
    }
}

function drawPaddle() {
    ctx.fillStyle = '#00d4ff';
    ctx.fillRect(paddle.x, paddle.y, paddle.width, paddle.height);
}

function drawBall() {
    ctx.beginPath();
    ctx.arc(ball.x, ball.y, ball.size, 0, Math.PI * 2);
    ctx.fillStyle = '#00d4ff';
    ctx.fill();
    ctx.closePath();
}

function drawBricks() {
    bricks.forEach(column => {
        column.forEach(brick => {
            if (brick.visible) {
                ctx.fillStyle = '#00d4ff';
                ctx.fillRect(brick.x, brick.y, brickInfo.width, brickInfo.height);
            }
        });
    });
}

function movePaddle() {
    paddle.x += paddle.dx;
    if (paddle.x < 0) paddle.x = 0;
    if (paddle.x + paddle.width > canvas.width) paddle.x = canvas.width - paddle.width;
}

function moveBall() {
    ball.x += ball.dx;
    ball.y += ball.dy;

    // Wall collision
    if (ball.x + ball.size > canvas.width || ball.x - ball.size < 0) ball.dx *= -1;
    if (ball.y - ball.size < 0) ball.dy *= -1;

    // Paddle collision
    if (ball.y + ball.size > paddle.y &&
        ball.x > paddle.x &&
        ball.x < paddle.x + paddle.width) {
        ball.dy = -ball.speed;
    }

    // Brick collision
    bricks.forEach(column => {
        column.forEach(brick => {
            if (brick.visible) {
                if (ball.x > brick.x &&
                    ball.x < brick.x + brickInfo.width &&
                    ball.y > brick.y &&
                    ball.y < brick.y + brickInfo.height) {
                    ball.dy *= -1;
                    brick.visible = false;
                    score += 10;
                    scoreElement.textContent = score;
                }
            }
        });
    });

    // Bottom wall collision (lose life)
    if (ball.y + ball.size > canvas.height) {
        lives--;
        livesElement.textContent = lives;
        if (lives === 0) {
            endGame(false);
        } else {
            resetBall();
        }
    }
}

function checkWinCondition() {
    const allBricksBroken = bricks.every(col => col.every(brick => !brick.visible));
    if (allBricksBroken) {
        endGame(true);
    }
}

function resetBall() {
    ball.x = canvas.width / 2;
    ball.y = paddle.y - 20;
    ball.dx = ball.speed * (Math.random() > 0.5 ? 1 : -1);
    ball.dy = -ball.speed;
}

function update() {
    if (gameOver) return;

    movePaddle();
    moveBall();

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    drawPaddle();
    drawBall();
    drawBricks();
    checkWinCondition();

    requestAnimationFrame(update);
}

function endGame(isWin) {
    gameOver = true;
    messageScreen.style.display = 'flex';
    if (isWin) {
        messageText.textContent = 'YOU WIN!';
    } else {
        messageText.textContent = 'GAME OVER';
    }
}

function resetGame() {
    gameOver = false;
    score = 0;
    lives = 3;
    scoreElement.textContent = score;
    livesElement.textContent = lives;
    messageScreen.style.display = 'none';
    createBricks();
    resetBall();
    paddle.x = canvas.width / 2 - paddle.width / 2;
    update();
}

function mouseMoveHandler(e) {
    const relativeX = e.clientX - canvas.getBoundingClientRect().left;
    if (relativeX > 0 && relativeX < canvas.width) {
        paddle.x = relativeX - paddle.width / 2;
    }
}

document.addEventListener('mousemove', mouseMoveHandler);
playAgainButton.addEventListener('click', resetGame);

resetGame();