from tensorflow.python.keras.layers import Conv2D, MaxPool2D, UpSampling2D, Conv2DTranspose, Input, Concatenate, Lambda, Dense, Reshape, BatchNormalization, Flatten
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.datasets import mnist
from tensorflow.python.keras.callbacks import TensorBoard
from tqdm import tqdm
import tensorflow as tf
import numpy as np
import argparse
import imageio
import os


def write_log(callback, names, logs, batch_no):
    for name, value in zip(names, logs):
        summary = tf.Summary()
        summary_value = summary.value.add()
        summary_value.simple_value = value
        summary_value.tag = name
        callback.writer.add_summary(summary, batch_no)
        callback.writer.flush()


def create_generator(input_shape):
    alpha = 2

    input_vec = Input(input_shape, name='input')
    x = Dense(128*7*7, activation='tanh', name='dense')(input_vec)
    x = BatchNormalization()(x)
    x = Reshape((7, 7, 128))(x)
    x = Conv2D(16 * alpha**2, (3, 3), activation='tanh', padding='same', name='conv_1')(x)
    x = Conv2DTranspose(64, (3, 3), strides=(2, 2), activation='tanh', padding='same', name='deconv_1')(x)
    x = Conv2D(16 * alpha, (3, 3), activation='tanh', padding='same', name='conv_2')(x)
    x = Conv2DTranspose(32, (3, 3), strides=(2, 2), activation='tanh', padding='same', name='deconv_2')(x)
    x = Conv2D(16, (3, 3), activation='tanh', padding='same', name='conv_3')(x)
    output = Conv2D(1, (3, 3), activation='tanh', padding='same', name='conv_4')(x)

    model = Model(input_vec, outputs=output)

    return model


def create_discriminator(input_shape=(28, 28, 1)):
    alpha = 2

    input_vec = Input(input_shape, name='input')
    x = Conv2D(16, (3, 3), activation='tanh', padding='same', name='d_conv_1')(input_vec)
    x = MaxPool2D((2, 2), padding='same')(x)
    x = Conv2D(16 * alpha, (3, 3), activation='tanh', padding='same', name='d_conv_2')(x)
    x = MaxPool2D((2, 2), padding='same')(x)
    x = Conv2D(16 * alpha**2, (3, 3), activation='tanh', padding='same', name='d_conv_3')(x)
    x = Flatten()(x)
    output = Dense(1, activation='sigmoid')(x)

    model = Model(input_vec, outputs=output)
    model.compile(loss='binary_crossentropy', optimizer='adadelta')

    return model


def set_trainable(model, trainable):
    for layer in model.layers:
        layer.trainable = trainable


def create_gan(input_size):
    generator = create_generator((input_size,))
    discriminator = create_discriminator()

    set_trainable(discriminator, False)
    input_vec = Input((input_size,), name='input')
    output = discriminator(generator(input_vec))

    gan = Model(input_vec, outputs=output)

    gan.compile(loss='binary_crossentropy', optimizer='adadelta')
    return gan, discriminator, generator


def create_random_vectors(samples, size, min=-1, max=1):
    return np.random.uniform(min, max, size=(samples, size))


def validate(generator, epoch, input_size, pred_dir):
    img_size = 28

    samples = create_random_vectors(25, input_size)
    pred = generator.predict_on_batch(samples)

    img = np.zeros((img_size*5, img_size*5, 1), dtype=np.uint8)
    for i, p in enumerate(pred):
        img[
            (i // 5)*img_size: ((i // 5)+1)*img_size,
            (i % 5)*img_size: ((i % 5) + 1)*img_size, :] = np.array((p * 127.5) + 127.5, dtype=np.uint8)

    imageio.imwrite(os.path.join(pred_dir, 'pred%d.png' % epoch), img)
    return


def train(input_size, batch_size, epochs, log_dir, pred_dir, model_dir):
    if not os.path.exists(pred_dir):
        os.makedirs(pred_dir)
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)

    gan, discriminator, generator = create_gan(input_size)

    (x_train_mnist, y_train_mnist), (x_test_mnist, y_test_mnist) = mnist.load_data()

    # Normalize mnist data between -1 and 1
    x_train_mnist = np.expand_dims((x_train_mnist - 127.5) / 127.5, axis=-1)
    x_test_mnist = np.expand_dims((x_test_mnist  - 127.5) / 127.5, axis=-1)

    batch_size = batch_size // 2
    y_batch_ones_generator = np.ones([batch_size*2, 1])

    callback = TensorBoard(log_dir=log_dir)
    callback.set_model(gan)

    step = 0
    for e in range(epochs):
        print('Epoch: %d/%d' % (e + 1, epochs))

        for i in tqdm(range(x_test_mnist.shape[0] // batch_size)):
            # Create batch data
            x_batch_mnist = x_train_mnist[i*batch_size:(i+1)*batch_size]
            noise_batch = create_random_vectors(batch_size, input_size)
            x_batch_generator = generator.predict_on_batch(noise_batch)

            # Train discriminator with label smoothing
            y_batch_ones = create_random_vectors(batch_size, 1, min=0.7, max=1)
            y_batch_zeros = create_random_vectors(batch_size, 1, min=0, max=0.3)

            discriminator_loss = discriminator.train_on_batch(
                np.concatenate((x_batch_mnist, x_batch_generator)),
                np.concatenate((y_batch_ones, y_batch_zeros)))

            # Train generator
            noise_batch = create_random_vectors(batch_size * 2, input_size)
            generator_loss = gan.train_on_batch(noise_batch, y_batch_ones_generator)
            write_log(
                callback, ['discriminator_train_loss', 'generator_train_loss'],
                [discriminator_loss, generator_loss], step)
            step += 1
        gan.save(os.path.join(model_dir, 'gan_%d.h5' % e))
        validate(generator, e, input_size, pred_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Train mnist dcgan')
    parser.add_argument(
        '-i', '--input-size', type=int, default=100,
        help='Input vector size to the generator')
    parser.add_argument(
        '-b', '--batch-size', type=int, default=128,
        help='Batch size')
    parser.add_argument(
        '-e', '--epochs', type=int, default=50,
        help='Number of epochs to train')
    parser.add_argument(
        '-l', '--log-dir', default='./log',
        help='Directory for tensorboard logs')
    parser.add_argument(
        '-p', '--pred-dir', default='./preds',
        help='Directory for generator predictions (one after each epoch)')
    parser.add_argument(
        '-m', '--model-dir', default='./models',
        help='Directory to save models')

    args = parser.parse_args()
    print(args)

    train(
        args.input_size, args.batch_size, args.epochs,
        args.log_dir, args.pred_dir, args.model_dir)