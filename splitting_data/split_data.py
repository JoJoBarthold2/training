import math
import pickle
from collections import Counter
import os
import pandas as pd
import gc
import psutil
import argparse
from tqdm import tqdm
import logging
import shutil
import time
from split_utils import NotEnoughDiskSpaceError, replace_special_chars
import numpy as np

logging.basicConfig(level=logging.INFO)


def split_words(data_path, skip_index, language, incongruent_words, dublicate_vectors):
    # Load the word counts
    words = pickle.load(open(f"word_counter_{language}.pkl", "rb"))

    # Initialize counters for test, validation, and training splits
    test_words = Counter()
    validation_words = Counter()
    training_words = Counter()

    # Remove incongruent words
    for word in incongruent_words["lexical_word"]:
        if word in words:
            words[word] -= 1
            logging.info(f"Removing one count of  {word} from words due to incongruent words")
            if words[word] == 0:
                del words[word]
    time.sleep(5)
    ## Remove words from dublicate vectors
    for word in dublicate_vectors["lexical_word"]:
        if word in words:
            words[word] -= 1
            logging.info(f"Removing one count of  {word} from words due to dublicate vectors")
            if words[word] == 0:
                del words[word]
    time.sleep(5)
    # Distribute word counts into test, validation, and training
    print(words.items())
    for word in words:

        word_count = words[word]
        ten_percent = math.ceil(word_count / 10)
        word_amount_for_test = ten_percent if ten_percent > 1 else 1
        test_words[word] = word_amount_for_test
        word_count -= word_amount_for_test
        word_amount_for_validation = (
            ten_percent
            if ten_percent < math.ceil(word_count / 2)
            else math.ceil(word_count / 2)
        )
        validation_words[word] = word_amount_for_validation
        word_count -= word_amount_for_validation
        training_words[word] = word_count
        assert (
            word_count + word_amount_for_validation + word_amount_for_test
            == words[word]
        )

    print(
        test_words["the"], validation_words["the"], training_words["the"], words["the"]
    )

    print(
        test_words.total(),
        validation_words.total(),
        training_words.total(),
        words.total(),
    )
    print(
        test_words.total() + validation_words.total() + training_words.total(),
        words.total(),
    )
    print(
        test_words.total() / words.total(),
        validation_words.total() / words.total(),
        training_words.total() / words.total(),
    )

    # Save the counters
    pickle.dump(test_words, open(f"test_words_{language}.pkl", "wb"))
    pickle.dump(validation_words, open(f"validation_words_{language}.pkl", "wb"))
    pickle.dump(training_words, open(f"training_words_{language}.pkl", "wb"))
    return split_data(
        data_path, skip_index, test_words, validation_words, training_words, language, dublicate_vectors
    )


def split_data(
    data_path,
    skip_index,
    test_words,
    validation_words,
    training_words,
    language,
    dublicate_vectors,
    data_size=5000,
):
    dir_names = []
    for name in ["validation", "training", "test"]:
        directory = name + "_counter_intermediates"
        dir_names.append(directory)
        if not os.path.exists(directory):
            os.makedirs(directory)

    validation_dir, training_dir, test_dir = dir_names
    # Process each file in the directory
    sorted_files = sorted(os.listdir(data_path))  # Sorting files for better debugging
    filtered_files = [
        file
        for file in sorted_files
        if file.startswith("corpus_as_df_mp_epoch_") and file.endswith(".pkl")
    ]
    sorted_files = filtered_files
    logging.info(sorted_files)
    i = 0
    test_df = pd.DataFrame()
    validation_df = pd.DataFrame()
    training_df = pd.DataFrame()
    test_index = 0
    validation_index = 0
    training_index = 0

    for file in tqdm(sorted_files):
        test_rows = []
        validation_rows = []
        training_rows = []
        if skip_index > 0:
            skip_index -= 1
            logging.info(f"Skipping {file}")
            continue

        if file.endswith(".pkl"):

            total, used, free = shutil.disk_usage(data_path)

            logging.info("Total: %d GiB" % (total // (2**30)))
            logging.info("Used: %d GiB" % (used // (2**30)))
            logging.info("Free: %d GiB" % (free // (2**30)))
            if free // (2**30) < 25:
                pickle.dump(
                    test_words,
                    open(
                        os.path.join(test_dir, f"test_words_{i}_{language}.pkl"), "wb"
                    ),
                )
                pickle.dump(
                    validation_words,
                    open(
                        os.path.join(
                            validation_dir, f"validation_words_{i}_{language}.pkl"
                        ),
                        "wb",
                    ),
                )
                pickle.dump(
                    training_words,
                    open(
                        os.path.join(
                            training_dir, f"training_words_{i}_{language}.pkl"
                        ),
                        "wb",
                    ),
                )

                raise NotEnoughDiskSpaceError()
            logging.info(f"Processing {file}")
            data = pd.read_pickle(os.path.join(data_path, file))
            dublicate_vectors.dropna(inplace=True)
            if isinstance(data, pd.DataFrame):

                # Split data based on the counters
                unique_identifier = file.split("df")[1]
                logging.debug(unique_identifier)
                logging.info("Now going through the data")
                for i, row in data.iterrows():
                    word = row["lexical_word"]

                    cleaned_word = replace_special_chars(word).lower()
                    cleaned_mfa_word = replace_special_chars(row["mfa_word"]).lower()
                    if cleaned_word != cleaned_mfa_word:
                        logging.warning(f"Word {word} is not the same as the mfa_word {row['mfa_word']} since no match for '{cleaned_word}' and '{cleaned_mfa_word}'")
                        continue
                   

                    if i % 1000 == 0:
                        logging.info(f"Processing row {i} of {len(data)}")
                    

                    mask = dublicate_vectors["lexical_word"] == cleaned_word
                    logging.debug(mask)
                    row_with_dublicate_vector = dublicate_vectors[
                        mask
                        ]
                    if len(row_with_dublicate_vector) > 0 and i in row_with_dublicate_vector.index:
                        logging.info(f"Skipping row with dublicate vector {word}")
                        continue

                    
                   
                    row["origin"] = (unique_identifier,i)
                    if test_words[word] > 0:
                        test_words[word] -= 1
                        test_rows.append(row)
                    elif validation_words[word] > 0:
                        validation_words[word] -= 1
                        validation_rows.append(row)
                    else:
                        training_words[word] -=1
                        training_rows.append(row)

                # Append rows to respective dataframes

                # we drop unnecessary columns
                test_df_i = pd.DataFrame(test_rows)
                if len(test_df_i) != 0:
                    print(test_df_i.columns)
                    test_df_i =  test_df_i[["lexical_word","cp_norm", "melspec_norm_recorded","melspec_norm_synthesized", "vector", "origin"]]

                validation_df_i = pd.DataFrame(validation_rows)
                if len(validation_df_i) != 0:

                    validation_df_i = validation_df_i[["lexical_word","cp_norm", "melspec_norm_recorded","melspec_norm_synthesized", "vector", "origin"]]

                training_df_i = pd.DataFrame(training_rows)
                if len(training_df_i) != 0:
                  training_df_i =  training_df_i[["lexical_word","cp_norm", "melspec_norm_recorded","melspec_norm_synthesized", "vector", "origin"]]


                test_df = pd.concat([test_df, test_df_i])
                validation_df = pd.concat([validation_df, validation_df_i])
                training_df = pd.concat([training_df, training_df_i])
              
              

                test_df_len = len(test_df)
                validation_df_len = len(validation_df)
                training_df_len = len(training_df)
                
               
                logging.info(f"train length: {training_df_len}")
                logging.info(f"validation length:  {validation_df_len}")
                logging.info(f"test length:  {test_df_len}")
                while test_df_len >= data_size:
                    test_df_i = test_df[:data_size]
                    test_df = test_df[data_size:]
                    file_path =f"test_data_{language}_{test_index}.pkl"
                    logging.info(f"writing test file:{file_path} ")
                    if len(test_df_i) != 0:
                        test_df_i.to_pickle(
                            os.path.join(
                                data_path, file_path
                            )
                        )
                    del test_df_i
                    test_index += 1
                    old_len = test_df_len
                    test_df_len = len(test_df)
                    logging.info(f"lenght of the test_file after writing :{test_df_len}")
                    assert old_len == test_df_len + data_size
                while validation_df_len >= data_size:
                   
                    validation_df_i = validation_df[:data_size]
                    validation_df = validation_df[data_size:]
                    file_path = f"validation_data_{language}_{validation_index}.pkl"
                    logging.info(f"writing validation file {file_path}")
                    if len(validation_df_i) != 0:
                        validation_df_i.to_pickle(
                            os.path.join(
                                data_path,
                                file_path,
                            )
                        )
                    del validation_df_i
                    validation_index += 1
                    old_len = validation_df_len
                    validation_df_len = len(validation_df)
                    logging.info(f"lenght of the validation_file after writing :{validation_df_len}")
                    assert old_len == validation_df_len + data_size
                while training_df_len >= data_size:
                   
                    training_df_i = training_df[:data_size]
                    training_df = training_df[data_size:]
                    file_path = f"training_data_{language}_{training_index}.pkl"
                    logging.info(f"writing training file {file_path}")
                    if len(training_df_i) != 0:
                        training_df_i.to_pickle(
                            os.path.join(
                                    data_path, file_path
                                )
                            )
                    del training_df_i
                    training_index += 1
                    old_len = training_df_len
                    training_df_len = len(training_df)
                    logging.info(f"lenght of the training_file after writing :{training_df_len}")
                    assert old_len == training_df_len + data_size
                # Free up memory
                del test_rows, validation_rows, training_rows
                if (
                    i % 10 == 0
                ):  # Save the counters every 10 files, so we can resume later
                    pickle.dump(
                        test_words, open(f"test_words_{i}_{language}.pkl", "wb")
                    )
                    pickle.dump(
                        validation_words,
                        open(f"validation_words_{i}_{language}.pkl", "wb"),
                    )
                    pickle.dump(
                        training_words, open(f"training_words_{i}_{language}.pkl", "wb")
                    )
                i += 1

            del data
            
            print(f"Memory usage: {psutil.virtual_memory().percent}%")

           

    def split_and_save_dataframe(df, data_size, data_path, base_filename="", index=i, language = "no_language_provided"):
        os.makedirs(data_path, exist_ok=True)  # Ensure directory exists
        if language == "no_language_provided":
            logging.warning("No language provided. This may cause issues with the data.")
            language = ""

        num_splits = (len(df) + data_size - 1) // data_size  # Ceiling division

        for j in range(num_splits):
            chunk = df[j * data_size : (j + 1) * data_size]  # Slice DataFrame
            chunk.to_pickle(os.path.join(data_path, f"{base_filename}_{language}_{index +j}.pkl"))

    split_and_save_dataframe(test_df, data_size, data_path, "test_data", test_index, language = language)
    split_and_save_dataframe(
        validation_df, data_size, data_path, "validation_data", validation_index, language = language
    )
    split_and_save_dataframe(
        training_df, data_size, data_path, "training_data", training_index, language = language
    )
    print("Data splitting completed successfully.")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Split data into test, validation, and training sets."
    )
    parser.add_argument(
        "--data_path",
        type=str,
        help="Path to the data directory w/o language.",
        default="../../../../../mnt/Restricted/Corpora/CommonVoiceVTL/corpus_as_df_mp_folder",
    )
    parser.add_argument(
        "--skip_index", type=int, help="Index of the file to skip.", default=0
    )
    parser.add_argument(
        "--split_words",
        action="store_true",
        help="Whether to split words or not.",
        default=False,
    )
    parser.add_argument(
        "--language", type=str, help="Language of the data.", default="de"
    )
    parser.add_argument(
        "--data_size", type=int, help="Size of the data in rows.", default=50000
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode.")
    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    language = args.language
    data_path = args.data_path + f"_{language}"

    skip_index = args.skip_index

    incongruent_words = pd.read_csv(f"incongruent_words_{language}.csv")
    dublicate_vectors = pd.read_csv(f"dublicate_vectors_{language}.csv")
    if args.split_words:
        split_words(data_path, skip_index, language, incongruent_words, dublicate_vectors)
    else:
        test_path = (
            f"test_words_{language}.pkl"
            if skip_index == 0
            else f"test_words_{skip_index}_{language}.pkl"
        )
        validation_path = (
            f"validation_words_{language}.pkl"
            if skip_index == 0
            else f"validation_words__{skip_index}_{language}.pkl"
        )  # this is a typo in the original code, it is fixed now so please be aware of this
        training_path = (
            f"training_words_{language}.pkl"
            if skip_index == 0
            else f"training_words_{skip_index}_{language}.pkl"
        )
        test_words = pickle.load(open(test_path, "rb"))
        validation_words = pickle.load(open(validation_path, "rb"))
        training_words = pickle.load(open(training_path, "rb"))
        split_data(
            data_path,
            skip_index,
            test_words,
            validation_words,
            training_words,
            language,
            dublicate_vectors,
            data_size=args.data_size,
           
    
        )
